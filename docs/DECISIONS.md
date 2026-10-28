# Decisões Arquiteturais (`DECISIONS.md`)

> Consolidação ativa das ADRs (`ADR-001` a `ADR-043` + Tooling). O texto histórico integral de cada ADR está preservado em `docs/archive/pre-slim-2026-10-25/DECISIONS.md`.

## 1. Fundação, Domínio, Mídia e Banco (`ADR-001` a `ADR-020`)

- **ADR-001 a ADR-004 (Operação Local e Runtime)**: Operação 100% local por padrão; Faster Whisper como engine primário; SQLite armazena exclusivamente metadados (nunca BLOBs de mídia); dados operacionais ficam em `%LOCALAPPDATA%\LocalTranscriber` fora do Git.
- **ADR-005 a ADR-008 (Mídia e Caminhos)**: Inspeção e decodificação obrigatórias via PyAV/FFmpeg; importação em blocos via arquivo temporário `.incoming` antes de move atômico; deduplicação determinística por SHA-256 exato dos bytes; persistência apenas de caminhos relativos normalizados com `/`, rejeitando `..`, drive letters ou caminhos absolutos.
- **ADR-009 a ADR-011 (Schema, FTS5 e Exportação)**: Migrações SQLite publicadas (v1–v4) são imutáveis e incrementais; pesquisa local usa SQLite FTS5 sincronizado por triggers; exportadores (`TXT`, `MD`, `SRT`, `VTT`, `JSON`) geram UTF-8 determinístico com `LF`.
- **ADR-012 a ADR-020 (Fronteiras, Modelos e CLI)**: FastAPI e UI vanilla sem CDN; proibido download silencioso de modelos (`models download --confirm` obrigatório e `local_files_only=True`); repositório `Local Transcriber` estritamente separado do `Local AI`; `TranscriptionEngine` desacoplado por protocolo; perfis `cpu` (`int8`), `cuda` (`int8_float16`, sem fallback silencioso) e `auto`; publicação transacional única de `Transcript` + `succeeded`; CLI unificada com `argparse`.

## 2. Fila, Concorrência, API Local e Interface Web (`ADR-021` a `ADR-036`)

- **ADR-021 a ADR-024 (Fila e Leases)**: Status público (`pending`, `running`, `succeeded`, `failed`, `cancelled`) separado de `JobPhase`; posse por lease renovável via heartbeat e execução `at least once`; publicação idempotente com eventos persistentes ordenados (`JobEvent`); worker sequencial único (concorrência 1) com cancelamento cooperativo.
- **ADR-025 a ADR-030 (API HTTP e SPA Vanilla)**: Core API sob `/api` restrita a `127.0.0.1:8765` com validação de `Host`/`Origin` local e lock de consumidor único; SSE reproduzido do SQLite via `Last-Event-ID`; mídia e exportações servidas apenas por UUID (com suporte a `Range` 206/416); UI vanilla empacotada no pacote Python usando apenas `textContent` (proibido `innerHTML`/`eval`) e regiões acessíveis `aria-live`.
- **ADR-031 a ADR-036 (Contenção SQLite, Monotonicidade, CUDA e Instalação)**:
  - **ADR-031**: Pré-consulta readonly antes de `BEGIN IMMEDIATE` para evitar locks em fila vazia, com retries curtos limitados para `SQLITE_BUSY`/`SQLITE_LOCKED`.
  - **ADR-032**: Gerações monotônicas e `AbortController` no frontend + cursor `last_event_sequence` por job no SSE.
  - **ADR-033**: Launcher `scripts/start-local-transcriber.ps1` em foreground para `127.0.0.1`.
  - **ADR-034**: Registro de DLLs CUDA 12 / cuDNN 9 restrito ao processo atual via `os.add_dll_directory`.
  - **ADR-035**: Exclusão de gravação com job `pending` ou `running` é recusada em transação imediata (409 Conflict).
  - **ADR-036**: Instalador guiado para usuários em venv isolado, sob licença de uso pessoal/não comercial (`LICENSE`).

## 3. Sumarização Opcional em Nuvem e Acesso Remoto Privado (`ADR-037` a `ADR-042`)

- **ADR-037 e ADR-038 (Sign in with ChatGPT — SIWC)**: Transporte `LLMTransport` desacoplado; `ChatGPTTransport` estritamente opt-in com OAuth 2.0 PKCE S256 / OIDC oficial, callback restrito a `127.0.0.1` com TTL de 10 min, validação RS256/JWKS em Python puro, preservação de `client_id` em `client_id.txt`, credenciais em `%LOCALAPPDATA%\LocalTranscriber\auth` protegidas por ACL NTFS (`icacls` fail-closed), exigência de `gpt-6-luna` em `/v1/models` sem fallback silencioso e streaming `/v1/responses` (`store: false`, `stream: true`) sem duplicação de deltas.
- **ADR-039 (Gateway Privado `remote_gateway.py` — Etapa 8J-A)**: Processo FastAPI separado (`127.0.0.1:8766`, `/remote/v1`, desligado por padrão), banco isolado `remote/gateway.sqlite3` (schema core v4 intocado), autenticação por cabeçalho `Tailscale-User-Login` em allowlist, bloqueio de `Tailscale-Funnel-Request`, validação estrita de `Host` bare e `Origin` HTTPS, cookie de sessão + CSRF HMAC-SHA256 (`remote/csrf.key` com ACL `icacls`), isolamento anti-IDOR por HMAC da identidade e upload com `Content-Length` obrigatório, limite de bytes, checagem de disco com lock e idempotência fail-closed (409 pós-crash se mídia já existir no core).
- **ADR-040, ADR-041 e ADR-042 (Sessão Temporária e Hardening — Etapa 8J-1 / Etapa 0)**:
  - Controle estritamente local via `remote-session start|status|stop` (serializado por `.session.lock`).
  - `ProcessVerifier` fail-closed com tipos Win32 64-bit (`wintypes.HANDLE`), tempo de criação e tokenização exata de `--session-id=<uuid>`.
  - `TailscaleCli`: proibição absoluta de Tailscale Funnel; desligamento seletivo (`tailscale serve --https=443 off`) executado somente se `serve status` comprovar posse exclusiva do mapping da sessão; `status` 100% observacional.
  - Journal persistido com `fsync`/`replace` antes de cada efeito (`prepared`, `gateway`, `activating`, `active`); estados incompletos ou falhas de rollback retêm o journal e bloqueiam novas mutações até reconciliação manual.

### ADR-043 — Upload resumable isolado e confirmação de importação (2026-10-26)

- Protocolo sequencial com manifesto SQLite exclusivo do gateway, chunks de 8 MiB (último parcial), hash por chunk e consolidado, flush/fsync/rename antes do commit do offset e serialização por sessão. O upload legado permanece disponível.
- O DDL resumable é aplicado idempotentemente sem tocar nas migrações do Core v4. Matéria, título e data ficam em tabela complementar `remote_resumable_metadata`, também no gateway, para permitir finalizar após reinício sem mudar o DDL contratado das sessões.
- Montagem em background e importação lógica via `MediaLibrary`; marcador `importing` durável antes do efeito no Core. Sem confirmação persistida de `recording_id`, recuperação falha fechada com `409 import_outcome_unknown`. Com confirmação, retry retoma somente enfileiramento/conclusão, usando a idempotência já existente de jobs. Nenhum worker concorrente de transcrição é criado.
- Reserva conservadora `min_free + 3*S + reservas ativas`, TTL fixo de 24 h, reconciliação no startup e GC periódico. Tombstones são retidos por pelo menos 7 dias e importações pendentes não são purgadas automaticamente. Homologação de queda de energia e rede física continua pendente.

## 4. Ferramentas de Desenvolvimento e Economia de Contexto (2026-10-25)

- MCPs `filesystem`, `github` separado (via `scripts/start-github-mcp.ps1` com token apenas em memória), `git`, `graphify` e `serena` (LSP/Pyright via `pipx` isolado) atuam exclusivamente no desenvolvimento, fora do runtime do aplicativo. Leitura de código segue a cadeia **Graphify → Serena (`find_symbol`)**, e operações GitHub usam exclusivamente o MCP `github` separado (proibido `codex_apps.github`).
## ADR — GET de status resumable sem Origin no navegador

Na interface remota da Etapa 8J-4, um GET da mesma origem pode chegar sem `Origin`. A fronteira aceita essa ausência apenas em `GET /remote/v1/uploads/resumable/{upload_id}` com ID hexadecimal de 32 caracteres, cookie de sessão válido, CSRF assinado e vinculado à identidade, `Sec-Fetch-Site: same-origin` e `Sec-Fetch-Mode: cors`, cada header único. `Origin` presente continua sujeito à allowlist; mutações e demais rotas resumable continuam exigindo `Origin`. A validação de loopback, Host, Funnel, identidade, ownership e rate limit permanece anterior à leitura.
