"""Sign in with ChatGPT OAuth 2.0 authentication and secure token management.

Implements official OpenID Connect (OIDC) / OAuth 2.0 for open-source local clients:
- PKCE S256 (RFC 7636) code verifier and challenge
- Dynamic client registration (dynamic_agent_client) and issued client_id preservation
- Persistent ext_agent_host_id (urn:uuid:...)
- Cryptographic state and nonce generation and verification
- ID token JWT RS256 signature verification against JWKS (RFC 3447 PKCS#1 v1.5)
- ID token claims validation (iss, aud, exp, nonce)
- chatgpt.tokens.use.direct scope
- Refresh token rotation
- Secure local token storage outside Git in runtime auth directory
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .exceptions import (
    ChatGPTAuthError,
    ChatGPTTokenRevokedError,
)

LOGGER = logging.getLogger(__name__)

OPENAI_AUTH_ISSUER = "https://auth.openai.com"
OPENAI_AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
OPENAI_JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
DEFAULT_CLIENT_ID = "dynamic_agent_client"
CHATGPT_SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
OPENAI_API_RESOURCE = "https://api.openai.com/v1"
AGENT_NAME_HINT = "Local Transcriber"
REQUIRED_SCOPES = frozenset({"openid", "resource.invoke", "chatgpt.tokens.use.direct"})

# ASN.1 DigestInfo prefix for SHA-256 (RFC 3447)
_ASN1_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def secure_file_permissions(path: Path) -> None:
    """Restrict file permissions strictly to current user, failing closed if not assured.

    On Windows (NT), uses icacls to strip inherited permissions and grant (R,W)
    strictly to the current user. Fails closed (raises ChatGPTAuthError) if the ACL
    cannot be assured.
    On POSIX platforms, uses os.chmod(stat.S_IRUSR | stat.S_IWUSR). We avoid claiming
    POSIX chmod provides file security on Windows.
    """
    if os.name == "nt":
        username = os.environ.get("USERNAME")
        if not username:
            raise ChatGPTAuthError(
                "Impossível determinar usuário do Windows para proteger o armazenamento de tokens."
            )
        try:
            cmd = ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(R,W)"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                raise ChatGPTAuthError(
                    f"Falha ao configurar ACL restrita no Windows "
                    f"(código {res.returncode}): {res.stderr.strip()}"
                )
        except Exception as err:
            if isinstance(err, ChatGPTAuthError):
                raise
            raise ChatGPTAuthError(
                f"Falha ao proteger arquivo de tokens no Windows com ACL restrita: {err}"
            ) from err
    else:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as err:
            raise ChatGPTAuthError(
                f"Falha ao aplicar permissões restritas POSIX no arquivo de tokens: {err}"
            ) from err


def b64url_decode(value: str) -> bytes:
    """Decode URL-safe base64 string with or without padding."""
    rem = len(value) % 4
    if rem > 0:
        value += "=" * (4 - rem)
    return base64.urlsafe_b64decode(value)


def b64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 string without trailing '=' padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge using SHA-256 (RFC 7636).

    Returns (code_verifier, code_challenge).
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = b64url_encode(digest)
    return verifier, challenge


def verify_rs256_signature(n: int, e: int, message: bytes, signature: bytes) -> bool:
    """Verify RSASSA-PKCS1-v1_5 signature using SHA-256 (RFC 3447).

    Implements modular exponentiation s^e mod n with standard library long integer
    arithmetic and verifies PKCS#1 v1.5 padding and DigestInfo structure.
    """
    k = (n.bit_length() + 7) // 8
    if len(signature) != k or k < 62:
        return False
    try:
        s_int = int.from_bytes(signature, "big")
        m_int = pow(s_int, e, n)
        em = m_int.to_bytes(k, "big")
    except Exception:
        return False

    # PKCS#1 v1.5 padding: 0x00 0x01 [0xFF]* 0x00 DigestInfo
    if em[0] != 0x00 or em[1] != 0x01:
        return False

    idx = 2
    while idx < len(em) and em[idx] == 0xFF:
        idx += 1

    # At least 8 bytes of 0xFF padding, followed by 0x00
    if idx < 10 or idx >= len(em) or em[idx] != 0x00:
        return False

    expected_digest_info = _ASN1_SHA256_PREFIX + hashlib.sha256(message).digest()
    return em[idx + 1 :] == expected_digest_info


@dataclass(frozen=True, slots=True)
class ChatGPTTokens:
    """Persisted ChatGPT OAuth token set."""

    access_token: str
    refresh_token: str | None
    id_token: str | None
    expires_at: float
    client_id: str
    ext_agent_host_id: str
    user_email: str | None = None
    account_id: str | None = None
    scope: str = CHATGPT_SCOPES

    def is_expired(self, buffer_seconds: float = 60.0) -> bool:
        """Check if access token has expired or will expire within buffer_seconds."""
        return time.time() + buffer_seconds >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatGPTTokens:
        return cls(
            access_token=str(data.get("access_token") or ""),
            refresh_token=data.get("refresh_token"),
            id_token=data.get("id_token"),
            expires_at=float(data.get("expires_at") or 0.0),
            client_id=str(data.get("client_id") or DEFAULT_CLIENT_ID),
            ext_agent_host_id=str(data.get("ext_agent_host_id") or ""),
            user_email=data.get("user_email"),
            account_id=data.get("account_id"),
            scope=str(data.get("scope") or CHATGPT_SCOPES),
        )


class ChatGPTTokenStore:
    """Secure on-disk token storage confined to local runtime auth directory."""

    def __init__(self, auth_dir: Path) -> None:
        self.auth_dir = auth_dir
        self.tokens_path = auth_dir / "chatgpt_tokens.json"
        self.host_id_path = auth_dir / "host_id.txt"
        self.client_id_path = auth_dir / "client_id.txt"

    def get_or_create_host_id(self) -> str:
        """Get or initialize a stable ext_agent_host_id (urn:uuid:...)."""
        if self.host_id_path.is_file():
            try:
                host_id = self.host_id_path.read_text(encoding="utf-8").strip()
                if host_id.startswith("urn:uuid:"):
                    return host_id
            except Exception:
                pass

        new_host_id = f"urn:uuid:{uuid.uuid4()}"
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        self.host_id_path.write_text(new_host_id, encoding="utf-8")
        return new_host_id

    def get_issued_client_id(self) -> str | None:
        """Get preserved client_id issued during dynamic client registration."""
        if self.client_id_path.is_file():
            try:
                cid = self.client_id_path.read_text(encoding="utf-8").strip()
                if cid:
                    return cid
            except Exception:
                pass
        tokens = self.load()
        if tokens and tokens.client_id and tokens.client_id != DEFAULT_CLIENT_ID:
            return tokens.client_id
        return None

    def save_issued_client_id(self, client_id: str) -> None:
        """Persist issued client_id for reauthorization with secure permissions."""
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.client_id_path.with_name(
            f"{self.client_id_path.name}.tmp.{secrets.token_hex(4)}"
        )
        try:
            temp_path.write_text(client_id.strip(), encoding="utf-8")
            secure_file_permissions(temp_path)
            temp_path.replace(self.client_id_path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def load(self) -> ChatGPTTokens | None:
        """Load stored tokens if file exists and is valid."""
        if not self.tokens_path.is_file():
            return None
        try:
            content = self.tokens_path.read_text(encoding="utf-8")
            data = json.loads(content)
            tokens = ChatGPTTokens.from_dict(data)
            if not tokens.access_token:
                return None
            return tokens
        except Exception as err:
            LOGGER.warning("Falha ao ler tokens do ChatGPT em %s: %s", self.tokens_path, err)
            return None

    def save(self, tokens: ChatGPTTokens) -> None:
        """Save tokens atomically with restricted file permissions."""
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        content = json.dumps(tokens.to_dict(), indent=2, ensure_ascii=False)
        temp_path = self.tokens_path.with_name(
            f"{self.tokens_path.name}.tmp.{secrets.token_hex(4)}"
        )
        try:
            temp_path.write_text(content, encoding="utf-8")
            secure_file_permissions(temp_path)
            temp_path.replace(self.tokens_path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

        if tokens.client_id and tokens.client_id != DEFAULT_CLIENT_ID:
            self.save_issued_client_id(tokens.client_id)

    def clear(self) -> None:
        """Securely delete the stored session tokens while preserving client identity."""
        if self.tokens_path.exists():
            try:
                self.tokens_path.unlink()
            except OSError as err:
                LOGGER.warning("Falha ao remover arquivo de tokens %s: %s", self.tokens_path, err)


def validate_id_token(
    id_token: str,
    *,
    expected_nonce: str | None = None,
    expected_client_id: str | None = None,
    jwks: dict[str, Any] | None = None,
    current_time: float | None = None,
) -> dict[str, Any]:
    """Validate OpenID Connect ID token signature and claims.

    Verifies:
    - JWT format (header.payload.signature)
    - alg == 'RS256'
    - kid exists in JWKS
    - RS256 signature verification (RFC 3447)
    - iss == 'https://auth.openai.com'
    - aud == expected_client_id (if supplied)
    - exp > current_time
    - nonce == expected_nonce (if supplied)
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ChatGPTAuthError("ID token inválido: formato JWT malformado (deve conter 3 partes).")

    header_b64, payload_b64, sig_b64 = parts

    try:
        header = json.loads(b64url_decode(header_b64).decode("utf-8"))
    except Exception as err:
        raise ChatGPTAuthError(f"ID token inválido: cabeçalho JSON ilegível: {err}") from err

    try:
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
    except Exception as err:
        raise ChatGPTAuthError(f"ID token inválido: payload JSON ilegível: {err}") from err

    if header.get("alg") != "RS256":
        raise ChatGPTAuthError(
            f"ID token inválido: algoritmo não suportado '{header.get('alg')}', esperado 'RS256'."
        )

    kid = header.get("kid")
    if not kid:
        raise ChatGPTAuthError("ID token inválido: 'kid' ausente no cabeçalho do token.")

    # Validate signature against JWKS if provided
    if jwks:
        keys = jwks.get("keys", [])
        matched_key = next((k for k in keys if k.get("kid") == kid and k.get("kty") == "RSA"), None)
        if not matched_key:
            raise ChatGPTAuthError(
                f"ID token inválido: chave com kid '{kid}' não encontrada no JWKS da OpenAI."
            )

        try:
            n_bytes = b64url_decode(str(matched_key["n"]))
            e_bytes = b64url_decode(str(matched_key["e"]))
            n_int = int.from_bytes(n_bytes, "big")
            e_int = int.from_bytes(e_bytes, "big")
            sig_bytes = b64url_decode(sig_b64)
            signed_bytes = f"{header_b64}.{payload_b64}".encode("ascii")

            if not verify_rs256_signature(n_int, e_int, signed_bytes, sig_bytes):
                raise ChatGPTAuthError(
                    "ID token inválido: falha na validação criptográfica da assinatura RS256."
                )
        except ChatGPTAuthError:
            raise
        except Exception as err:
            raise ChatGPTAuthError(f"Erro ao verificar assinatura do ID token: {err}") from err

    # Claims validation
    iss = payload.get("iss")
    if iss != OPENAI_AUTH_ISSUER:
        raise ChatGPTAuthError(
            f"ID token inválido: emissor (iss) '{iss}' não corresponde a '{OPENAI_AUTH_ISSUER}'."
        )

    now = current_time if current_time is not None else time.time()
    exp = float(payload.get("exp") or 0.0)
    if now >= exp:
        raise ChatGPTAuthError(f"ID token expirado (exp={exp}, agora={now}).")

    if expected_client_id:
        aud = payload.get("aud")
        if isinstance(aud, list):
            if expected_client_id not in aud:
                raise ChatGPTAuthError(
                    f"ID token inválido: audiência '{aud}' não inclui client_id "
                    f"'{expected_client_id}'."
                )
        elif aud != expected_client_id and expected_client_id != DEFAULT_CLIENT_ID:
            raise ChatGPTAuthError(
                f"ID token inválido: audiência '{aud}' não corresponde a client_id "
                f"'{expected_client_id}'."
            )

    if expected_nonce:
        nonce = payload.get("nonce")
        if nonce != expected_nonce:
            raise ChatGPTAuthError(
                f"ID token inválido: nonce '{nonce}' não confere com nonce enviado "
                f"'{expected_nonce}'."
            )

    return payload


class ChatGPTAuthManager:
    """Manages Sign in with ChatGPT OAuth 2.0 flow, token rotation, and status."""

    def __init__(
        self,
        auth_dir: Path,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        authorize_url: str = OPENAI_AUTHORIZE_URL,
        token_url: str = OPENAI_TOKEN_URL,
        jwks_url: str = OPENAI_JWKS_URL,
        timeout: float = 30.0,
    ) -> None:
        self.store = ChatGPTTokenStore(auth_dir)
        self.default_client_id = client_id
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.jwks_url = jwks_url
        self.timeout = timeout
        self._cached_jwks: dict[str, Any] | None = None
        self._cached_jwks_time: float = 0.0

    @property
    def host_id(self) -> str:
        return self.store.get_or_create_host_id()

    @property
    def client_id(self) -> str:
        issued = self.store.get_issued_client_id()
        if issued:
            return issued
        return self.default_client_id

    def create_authorization_url(
        self,
        redirect_uri: str,
        *,
        state: str | None = None,
        nonce: str | None = None,
    ) -> tuple[str, str, str, str]:
        """Generate PKCE pair, state, nonce, and the complete OAuth authorize URL.

        Conforms to OpenAI Sign in with ChatGPT specification:
        - Includes scopes openid profile email offline_access resource.invoke
          chatgpt.tokens.use.direct
        - Includes resource https://api.openai.com/v1
        - Includes agent_name_hint on initial registration; omits it on reauthorization
        - Includes id_token_hint from saved account on reauthorization if available
        Returns (authorize_url, code_verifier, state, nonce).
        """
        code_verifier, code_challenge = generate_pkce_pair()
        state_val = state or secrets.token_urlsafe(32)
        nonce_val = nonce or secrets.token_urlsafe(32)

        issued_cid = self.store.get_issued_client_id()
        is_reauthorization = bool(issued_cid and issued_cid != DEFAULT_CLIENT_ID)

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": CHATGPT_SCOPES,
            "resource": OPENAI_API_RESOURCE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state_val,
            "nonce": nonce_val,
            "ext_agent_host_id": self.host_id,
        }

        if is_reauthorization:
            # On reauthorization, omit agent_name_hint and include id_token_hint if available
            saved_tokens = self.store.load()
            if saved_tokens and saved_tokens.id_token:
                params["id_token_hint"] = saved_tokens.id_token
        else:
            params["agent_name_hint"] = AGENT_NAME_HINT

        query_str = urllib.parse.urlencode(params)
        auth_url = f"{self.authorize_url}?{query_str}"
        return auth_url, code_verifier, state_val, nonce_val

    def fetch_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch and cache JWKS keys from OpenAI JWKS endpoint."""
        now = time.time()
        if not force_refresh and self._cached_jwks and (now - self._cached_jwks_time < 3600):
            return self._cached_jwks

        req = urllib.request.Request(
            self.jwks_url,
            headers={"Accept": "application/json", "User-Agent": "LocalTranscriber/0.7.1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._cached_jwks = data
                self._cached_jwks_time = now
                return data
        except Exception as err:
            if self._cached_jwks:
                return self._cached_jwks
            raise ChatGPTAuthError(
                f"Falha ao obter chaves JWKS em '{self.jwks_url}': {err}"
            ) from err

    def exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        *,
        expected_nonce: str | None = None,
        expected_client_id: str | None = None,
        client_id: str | None = None,
    ) -> ChatGPTTokens:
        """Exchange authorization code for access, refresh, and ID tokens."""
        client_to_use = (
            client_id or expected_client_id or self.store.get_issued_client_id() or self.client_id
        )
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_to_use,
            "code_verifier": code_verifier,
            "resource": OPENAI_API_RESOURCE,
        }
        body_bytes = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.token_url,
            data=body_bytes,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "LocalTranscriber/0.7.1",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_text = ""
            try:
                err_text = err.read().decode("utf-8")
            except Exception:
                pass
            raise ChatGPTAuthError(
                f"Falha na troca de código por token (HTTP {err.code}): {err_text}"
            ) from err
        except Exception as err:
            raise ChatGPTAuthError(
                f"Erro de conexão ao trocar código de autorização: {err}"
            ) from err

        access_token = str(resp_data.get("access_token") or "")
        if not access_token:
            raise ChatGPTAuthError("Resposta de token não contém access_token válido.")

        # Client ID verification and preservation
        saved_issued_id = self.store.get_issued_client_id()
        returned_client_id = resp_data.get("client_id") or (
            client_to_use if client_to_use != DEFAULT_CLIENT_ID else None
        )

        if not saved_issued_id or saved_issued_id == DEFAULT_CLIENT_ID:
            # First registration: OpenAI must issue a client_id
            if not returned_client_id:
                raise ChatGPTAuthError(
                    "Resposta de token da inscrição inicial não contém 'client_id' emitido."
                )
            issued_client_id = str(returned_client_id).strip()
            self.store.save_issued_client_id(issued_client_id)
        else:
            # Reauthorization: preserve original client_id and reject unexpected change
            if returned_client_id and str(returned_client_id).strip() != saved_issued_id:
                raise ChatGPTAuthError(
                    f"Troca inesperada de client_id durante reautorização: "
                    f"esperado '{saved_issued_id}', recebido '{returned_client_id}'."
                )
            issued_client_id = saved_issued_id

        # Mandatory ID Token validation
        id_token = resp_data.get("id_token")
        if not id_token:
            raise ChatGPTAuthError("ID token obrigatório ausente na resposta de token do ChatGPT.")

        jwks = self.fetch_jwks()
        claims = validate_id_token(
            id_token,
            expected_nonce=expected_nonce,
            expected_client_id=issued_client_id,
            jwks=jwks,
        )
        user_email = claims.get("email")
        account_id = claims.get("sub") or claims.get("account_id")

        # Mandatory Scopes validation
        granted_scope_str = str(resp_data.get("scope") or "")
        granted_scopes = set(granted_scope_str.split())
        missing_scopes = REQUIRED_SCOPES - granted_scopes
        if missing_scopes:
            raise ChatGPTAuthError(
                "Escopos concedidos insuficientes na resposta de autorização: "
                f"ausente {sorted(missing_scopes)}."
            )

        refresh_token = resp_data.get("refresh_token")
        expires_in = float(resp_data.get("expires_in") or 3600.0)
        expires_at = time.time() + expires_in

        tokens = ChatGPTTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            expires_at=expires_at,
            client_id=issued_client_id,
            ext_agent_host_id=self.host_id,
            user_email=user_email,
            account_id=account_id,
            scope=granted_scope_str,
        )

        self.store.save(tokens)
        return tokens

    def refresh_access_token(self) -> ChatGPTTokens:
        """Refresh the access token using the stored refresh_token (token rotation)."""
        tokens = self.store.load()
        if not tokens or not tokens.refresh_token:
            raise ChatGPTAuthError("Nenhum refresh token disponível para renovação de sessão.")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": tokens.client_id,
            "resource": OPENAI_API_RESOURCE,
        }
        body_bytes = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.token_url,
            data=body_bytes,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "LocalTranscriber/0.7.1",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_text = ""
            try:
                err_text = err.read().decode("utf-8")
            except Exception:
                pass
            if err.code in (400, 401):
                self.store.clear()
                raise ChatGPTTokenRevokedError(
                    f"Refresh token revogado ou inválido (HTTP {err.code}): {err_text}"
                ) from err
            raise ChatGPTAuthError(
                f"Erro HTTP {err.code} ao renovar token do ChatGPT: {err_text}"
            ) from err
        except Exception as err:
            raise ChatGPTAuthError(f"Falha de conexão ao renovar token: {err}") from err

        access_token = str(resp_data.get("access_token") or "")
        if not access_token:
            raise ChatGPTAuthError("Renovação de token não retornou access_token válido.")

        # Handle refresh token rotation: prefer new refresh_token if returned
        new_refresh_token = resp_data.get("refresh_token") or tokens.refresh_token
        new_id_token = resp_data.get("id_token") or tokens.id_token
        expires_in = float(resp_data.get("expires_in") or 3600.0)
        expires_at = time.time() + expires_in
        new_client_id = str(resp_data.get("client_id") or tokens.client_id)

        user_email = tokens.user_email
        account_id = tokens.account_id
        if new_id_token and new_id_token != tokens.id_token:
            try:
                jwks = self.fetch_jwks()
                claims = validate_id_token(
                    new_id_token,
                    expected_client_id=new_client_id,
                    jwks=jwks,
                )
                user_email = claims.get("email") or user_email
                account_id = claims.get("sub") or account_id
            except Exception:
                pass

        new_tokens = ChatGPTTokens(
            access_token=access_token,
            refresh_token=new_refresh_token,
            id_token=new_id_token,
            expires_at=expires_at,
            client_id=new_client_id,
            ext_agent_host_id=tokens.ext_agent_host_id,
            user_email=user_email,
            account_id=account_id,
            scope=str(resp_data.get("scope") or tokens.scope),
        )

        self.store.save(new_tokens)
        return new_tokens

    def get_valid_token(self) -> str:
        """Return a valid access token, refreshing automatically if close to expiration."""
        tokens = self.store.load()
        if not tokens or not tokens.access_token:
            raise ChatGPTAuthError(
                "Nenhuma sessão do ChatGPT conectada. Faça login via 'Sign in with ChatGPT'."
            )

        if tokens.is_expired():
            tokens = self.refresh_access_token()

        return tokens.access_token

    def get_status(self) -> dict[str, Any]:
        """Return safe authentication status information without exposing secret tokens."""
        tokens = self.store.load()
        if not tokens or not tokens.access_token:
            return {
                "connected": False,
                "email": None,
                "account_id": None,
                "client_id": self.default_client_id,
                "expires_at": None,
                "expired": True,
            }

        return {
            "connected": True,
            "email": tokens.user_email,
            "account_id": tokens.account_id,
            "client_id": tokens.client_id,
            "expires_at": tokens.expires_at,
            "expired": tokens.is_expired(),
        }

    def logout(self) -> None:
        """Log out and erase persisted token data."""
        self.store.clear()
