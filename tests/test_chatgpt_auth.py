"""Deterministic validation tests for ChatGPT OAuth, PKCE, state/nonce, and JWKS verification."""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_transcriber.chatgpt_auth import (
    OPENAI_AUTH_ISSUER,
    ChatGPTAuthManager,
    ChatGPTTokens,
    ChatGPTTokenStore,
    b64url_encode,
    generate_pkce_pair,
    validate_id_token,
    verify_rs256_signature,
)
from local_transcriber.exceptions import (
    ChatGPTAuthError,
    ChatGPTTokenRevokedError,
)

# ---------------------------------------------------------------------------
# Helpers for RSA test key generation (pure Python Miller-Rabin)
# ---------------------------------------------------------------------------


def _is_prime(n: int, k: int = 25) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29):
        if n % p == 0:
            return n == p
    s, d = 0, n - 1
    while d % 2 == 0:
        s += 1
        d //= 2
    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _get_prime(bits: int) -> int:
    while True:
        p = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_prime(p):
            return p


def _make_test_rsa_key(bits: int = 512) -> tuple[int, int, int]:
    """Return (n, e, d) for synthetic testing."""
    p = _get_prime(bits)
    q = _get_prime(bits)
    n = p * q
    phi = (p - 1) * (q - 1)
    e = 65537
    d = pow(e, -1, phi)
    return n, e, d


def _sign_pkcs1_v15_sha256(message: bytes, d: int, n: int) -> bytes:
    """Produce valid RSASSA-PKCS1-v1_5 signature."""
    k = (n.bit_length() + 7) // 8
    asn1_sha256 = bytes.fromhex("3031300d060960864801650304020105000420")
    t = asn1_sha256 + hashlib.sha256(message).digest()
    ps_len = k - len(t) - 3
    em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
    m_int = int.from_bytes(em, "big")
    s_int = pow(m_int, d, n)
    return s_int.to_bytes(k, "big")


def _make_jwt(header: dict, payload: dict, d: int, n: int) -> str:
    h_b64 = b64url_encode(json.dumps(header).encode("utf-8"))
    p_b64 = b64url_encode(json.dumps(payload).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = _sign_pkcs1_v15_sha256(signing_input, d, n)
    s_b64 = b64url_encode(sig)
    return f"{h_b64}.{p_b64}.{s_b64}"


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_pkce_generation() -> None:
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43
    # Check S256 derivation
    expected = b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    assert challenge == expected


def test_state_and_nonce_in_auth_url(tmp_path: Path) -> None:
    mgr = ChatGPTAuthManager(tmp_path / "auth")
    url, verifier, state, nonce = mgr.create_authorization_url("http://127.0.0.1:8765/callback")

    assert "https://auth.openai.com/api/accounts/authorize?" in url
    assert f"client_id={mgr.client_id}" in url
    assert f"state={state}" in url
    assert f"nonce={nonce}" in url
    assert "code_challenge_method=S256" in url
    expected_scope = (
        "scope=openid+profile+email+offline_access+resource.invoke+chatgpt.tokens.use.direct"
    )
    assert expected_scope in url
    assert "resource=https%3A%2F%2Fapi.openai.com%2Fv1" in url
    assert "ext_agent_host_id=urn%3Auuid%3A" in url
    assert "agent_name_hint=Local+Transcriber" in url

    # Test reauthorization behavior: save issued client_id and id_token
    mgr.store.save_issued_client_id("oaiapp_registered_xyz")
    dummy_tokens = ChatGPTTokens(
        access_token="at_dummy",
        refresh_token="rt_dummy",
        id_token="saved_id_token_abc",
        expires_at=time.time() + 3600,
        client_id="oaiapp_registered_xyz",
        ext_agent_host_id=mgr.host_id,
    )
    mgr.store.save(dummy_tokens)

    reauth_url, _, _, _ = mgr.create_authorization_url("http://127.0.0.1:8765/callback")
    assert "client_id=oaiapp_registered_xyz" in reauth_url
    assert "agent_name_hint" not in reauth_url
    assert "id_token_hint=saved_id_token_abc" in reauth_url


def test_rsa_pkcs1_v15_signature_verification() -> None:
    n, e, d = _make_test_rsa_key(512)
    message = b"Synthetic message for Sign in with ChatGPT validation"
    sig = _sign_pkcs1_v15_sha256(message, d, n)

    assert verify_rs256_signature(n, e, message, sig) is True
    # Tampered message
    assert verify_rs256_signature(n, e, b"Tampered message", sig) is False
    # Bad signature
    bad_sig = bytearray(sig)
    bad_sig[10] ^= 0xFF
    assert verify_rs256_signature(n, e, message, bytes(bad_sig)) is False


def test_validate_id_token_success() -> None:
    n, e, d = _make_test_rsa_key(512)
    kid = "test-key-01"
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": kid,
                "n": b64url_encode(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                "e": b64url_encode(e.to_bytes((e.bit_length() + 7) // 8, "big")),
            }
        ]
    }

    now = time.time()
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    payload = {
        "iss": OPENAI_AUTH_ISSUER,
        "aud": "oaiapp_test_123",
        "exp": now + 3600,
        "nonce": "test-nonce-xyz",
        "sub": "user_456",
        "email": "student@example.org",
    }

    jwt_str = _make_jwt(header, payload, d, n)

    claims = validate_id_token(
        jwt_str,
        expected_nonce="test-nonce-xyz",
        expected_client_id="oaiapp_test_123",
        jwks=jwks,
        current_time=now,
    )
    assert claims["email"] == "student@example.org"
    assert claims["sub"] == "user_456"


def test_validate_id_token_claims_rejections() -> None:
    n, e, d = _make_test_rsa_key(512)
    kid = "test-key-01"
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": kid,
                "n": b64url_encode(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                "e": b64url_encode(e.to_bytes((e.bit_length() + 7) // 8, "big")),
            }
        ]
    }

    now = time.time()
    header = {"alg": "RS256", "kid": kid}

    # 1. Invalid issuer
    bad_iss = {"iss": "https://evil.com", "aud": "oaiapp_1", "exp": now + 100}
    jwt1 = _make_jwt(header, bad_iss, d, n)
    with pytest.raises(ChatGPTAuthError, match="emissor"):
        validate_id_token(jwt1, jwks=jwks, current_time=now)

    # 2. Expired token
    expired = {"iss": OPENAI_AUTH_ISSUER, "aud": "oaiapp_1", "exp": now - 10}
    jwt2 = _make_jwt(header, expired, d, n)
    with pytest.raises(ChatGPTAuthError, match="expirado"):
        validate_id_token(jwt2, jwks=jwks, current_time=now)

    # 3. Nonce mismatch
    bad_nonce = {"iss": OPENAI_AUTH_ISSUER, "aud": "oaiapp_1", "exp": now + 100, "nonce": "A"}
    jwt3 = _make_jwt(header, bad_nonce, d, n)
    with pytest.raises(ChatGPTAuthError, match="nonce"):
        validate_id_token(jwt3, expected_nonce="B", jwks=jwks, current_time=now)

    # 4. Audience mismatch
    bad_aud = {"iss": OPENAI_AUTH_ISSUER, "aud": "oaiapp_other", "exp": now + 100}
    jwt4 = _make_jwt(header, bad_aud, d, n)
    with pytest.raises(ChatGPTAuthError, match="audiência"):
        validate_id_token(jwt4, expected_client_id="oaiapp_mine", jwks=jwks, current_time=now)


def test_token_store_outside_git(tmp_path: Path) -> None:
    auth_dir = tmp_path / "runtime" / "auth"
    store = ChatGPTTokenStore(auth_dir)

    tokens = ChatGPTTokens(
        access_token="test_access_token_123",
        refresh_token="test_refresh_token_456",
        id_token="test_id_token_789",
        expires_at=time.time() + 3600,
        client_id="oaiapp_app_xyz",
        ext_agent_host_id=store.get_or_create_host_id(),
        user_email="user@test.org",
    )
    store.save(tokens)

    assert store.tokens_path.is_file()
    assert store.client_id_path.is_file()
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "test_access_token_123"
    assert loaded.client_id == "oaiapp_app_xyz"
    assert loaded.user_email == "user@test.org"
    assert store.get_issued_client_id() == "oaiapp_app_xyz"

    # Test clearing tokens: tokens_path deleted, but client identity preserved
    store.clear()
    assert not store.tokens_path.exists()
    assert store.load() is None
    assert store.client_id_path.is_file()
    assert store.get_issued_client_id() == "oaiapp_app_xyz"


def test_exchange_code_mocked(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    n, e, d = _make_test_rsa_key(512)
    kid = "test-key-jwks"
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": kid,
                "n": b64url_encode(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                "e": b64url_encode(e.to_bytes((e.bit_length() + 7) // 8, "big")),
            }
        ]
    }

    now = time.time()
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    payload = {
        "iss": OPENAI_AUTH_ISSUER,
        "aud": "oaiapp_issued_999",
        "exp": now + 3600,
        "nonce": "test_nonce_val",
        "sub": "user_123",
        "email": "user@test.org",
    }
    valid_id_token = _make_jwt(header, payload, d, n)

    mock_resp_data = {
        "access_token": "at_mock_abc",
        "refresh_token": "rt_mock_def",
        "id_token": valid_id_token,
        "expires_in": 3600,
        "client_id": "oaiapp_issued_999",
        "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch("urllib.request.urlopen", return_value=mock_resp) as mock_url,
        patch.object(mgr, "fetch_jwks", return_value=jwks),
    ):
        tokens = mgr.exchange_code(
            "mock_auth_code",
            "verifier_123",
            "http://127.0.0.1:8765/cb",
            expected_nonce="test_nonce_val",
        )
        assert tokens.access_token == "at_mock_abc"
        assert tokens.refresh_token == "rt_mock_def"
        assert tokens.id_token == valid_id_token
        assert tokens.client_id == "oaiapp_issued_999"
        assert mgr.client_id == "oaiapp_issued_999"

        # Verify resource parameter was sent in token exchange request
        req_sent = mock_url.call_args[0][0]
        req_body = req_sent.data.decode("utf-8")
        assert "resource=https%3A%2F%2Fapi.openai.com%2Fv1" in req_body


def test_exchange_code_missing_id_token_rejected(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    mock_resp_data = {
        "access_token": "at_mock_abc",
        "refresh_token": "rt_mock_def",
        "client_id": "oaiapp_issued_999",
        "scope": "openid resource.invoke chatgpt.tokens.use.direct",
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ChatGPTAuthError, match="ID token obrigatório ausente"):
            mgr.exchange_code("code", "verifier", "http://127.0.0.1:8765/cb")


def test_exchange_code_missing_scopes_rejected(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    n, e, d = _make_test_rsa_key(512)
    kid = "k1"
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": kid,
                "n": b64url_encode(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                "e": b64url_encode(e.to_bytes((e.bit_length() + 7) // 8, "big")),
            }
        ]
    }
    id_token = _make_jwt(
        {"alg": "RS256", "kid": kid},
        {"iss": OPENAI_AUTH_ISSUER, "aud": "oaiapp_1", "exp": time.time() + 3600},
        d,
        n,
    )

    # Missing resource.invoke and chatgpt.tokens.use.direct
    mock_resp_data = {
        "access_token": "at_mock_abc",
        "id_token": id_token,
        "client_id": "oaiapp_1",
        "scope": "openid profile email",
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch("urllib.request.urlopen", return_value=mock_resp),
        patch.object(mgr, "fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ChatGPTAuthError, match="Escopos concedidos insuficientes"):
            mgr.exchange_code("code", "verifier", "http://127.0.0.1:8765/cb")


def test_exchange_code_first_registration_missing_client_id_rejected(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    mock_resp_data = {
        "access_token": "at_mock_abc",
        # client_id absent on first registration
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ChatGPTAuthError, match="inscrição inicial não contém 'client_id'"):
            mgr.exchange_code("code", "verifier", "http://127.0.0.1:8765/cb")


def test_exchange_code_reauthorization_swap_client_id_rejected(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)
    mgr.store.save_issued_client_id("oaiapp_original_123")

    mock_resp_data = {
        "access_token": "at_mock_abc",
        "client_id": "oaiapp_different_456",  # Unexpected swap!
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ChatGPTAuthError, match="Troca inesperada de client_id"):
            mgr.exchange_code("code", "verifier", "http://127.0.0.1:8765/cb")


def test_refresh_token_sends_resource(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    initial_tokens = ChatGPTTokens(
        access_token="old_access_token",
        refresh_token="old_refresh_token",
        id_token=None,
        expires_at=time.time() - 10,
        client_id="oaiapp_issued_999",
        ext_agent_host_id=mgr.host_id,
    )
    mgr.store.save(initial_tokens)

    rotated_resp_data = {
        "access_token": "new_access_token",
        "refresh_token": "rotated_refresh_token_xyz",
        "expires_in": 3600,
        "client_id": "oaiapp_issued_999",
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(rotated_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_url:
        new_token = mgr.get_valid_token()
        assert new_token == "new_access_token"
        req_sent = mock_url.call_args[0][0]
        req_body = req_sent.data.decode("utf-8")
        assert "resource=https%3A%2F%2Fapi.openai.com%2Fv1" in req_body


def test_refresh_token_rotation(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    initial_tokens = ChatGPTTokens(
        access_token="old_access_token",
        refresh_token="old_refresh_token",
        id_token=None,
        expires_at=time.time() - 10,  # expired
        client_id="oaiapp_issued_999",
        ext_agent_host_id=mgr.host_id,
    )
    mgr.store.save(initial_tokens)

    # 1. Successful rotation
    rotated_resp_data = {
        "access_token": "new_access_token",
        "refresh_token": "rotated_refresh_token_xyz",
        "expires_in": 3600,
        "client_id": "oaiapp_issued_999",
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(rotated_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        new_token = mgr.get_valid_token()
        assert new_token == "new_access_token"
        loaded = mgr.store.load()
        assert loaded is not None
        assert loaded.refresh_token == "rotated_refresh_token_xyz"


def test_refresh_token_revocation_clears_store(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    mgr = ChatGPTAuthManager(auth_dir)

    initial_tokens = ChatGPTTokens(
        access_token="old_access_token",
        refresh_token="revoked_refresh_token",
        id_token=None,
        expires_at=time.time() - 10,
        client_id="oaiapp_issued_999",
        ext_agent_host_id=mgr.host_id,
    )
    mgr.store.save(initial_tokens)

    import urllib.error

    http_err = urllib.error.HTTPError(
        url="https://auth.openai.com/api/accounts/oauth/token",
        code=400,
        msg="Bad Request",
        hdrs={},  # type: ignore[arg-type]
        fp=MagicMock(read=lambda: b'{"error":"invalid_grant"}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(ChatGPTTokenRevokedError):
            mgr.get_valid_token()

    # Store must be cleared after token revocation
    assert mgr.store.load() is None


def test_secure_file_permissions(tmp_path: Path) -> None:
    from local_transcriber.chatgpt_auth import secure_file_permissions

    target_file = tmp_path / "secret.json"
    target_file.write_text('{"token": "secret"}', encoding="utf-8")

    # Should succeed on the current platform without error
    secure_file_permissions(target_file)
    assert target_file.is_file()

    # Fail closed on Windows if username cannot be resolved
    with patch("os.name", "nt"), patch("os.environ.get", return_value=None):
        with pytest.raises(ChatGPTAuthError, match="Impossível determinar usuário"):
            secure_file_permissions(target_file)
