# Estado atual do projeto (`Local Transcriber`)

> Atualizado em: 2026-10-27. Histórico detalhado das fases 1 a 8I preservado em `docs/archive/pre-slim-2026-10-25/` e nos relatórios `docs/PHASE_*.md`.

## Fotografia Técnica Atual

- **Versão do pacote**: `0.7.1` | **Schema SQLite core**: `v4` | **Python**: `>=3.11` (validado em 3.13 x64).
- **Suíte de testes confirmada**: **473 testes aprovados** na suíte completa (incluindo 120 de gateway remoto, 53 de upload resumable, 101 de sessão remota, 36 de ChatGPT/SIWC, 26 de sumarização e 24 de fila/leases). Ruff `check`, formatação dos arquivos Python alterados e `pip check` aprovados; a formatação global aponta blocos Python em dois documentos preexistentes da Etapa 2, preservados nesta entrega.
- **Módulos ativos em `src/local_transcriber/`**:
  - **Core e Persistência**: `config.py` (`%LOCALAPPDATA%\LocalTranscriber`), `models.py`, `database.py` (SQLite v4), `repository.py` (FTS5 Unicode parametrizado), `media.py` (importação atômica PyAV + SHA-256, bloqueio de exclusão com job ativo), `exporters.py` (`TXT`, `MD`, `SRT`, `VTT`, `JSON`).
  - **Transcrição e Fila**: `models_manager.py` (download só com `--confirm`), `transcription.py` (`FasterWhisperEngine` com `local_files_only=True`, perfis `cpu` `int8`, `cuda` `int8_float16` via `os.add_dll_directory` e `auto`), `queueing.py` (fila persistente, pré-consulta readonly antes de `BEGIN IMMEDIATE`, leases com heartbeat e `LeaseOwnershipLost`).
  - **API Local e Web (`127.0.0.1:8765`)**: `api.py` (FastAPI loopback, consumidor único, Range de mídia, SSE incremental com cursor `last_event_sequence` e `Last-Event-ID`, sem CDN/Swagger externo) e `web/` (UI vanilla com estados assíncronos monotônicos, `textContent` seguro e painel interativo de resumo).
  - **Sumarização Estruturada (`summarizer.py`)**: Map-Reduce temporal em blocos de 20 min gerando `.resumo.md` e `.resumo.json` (schema 1.0.0: `executive`, `timeline`, `glossary`, `charts`, `flashcards`, `spoken_summary`) via `LLMTransport`:
    1. `OllamaTransport` (padrão offline em `127.0.0.1:11434`, `qwen2.5:3b`);
    2. `ChatGPTTransport` (`chatgpt_auth.py` + `chatgpt_client.py`, opt-in via OAuth 2.0 PKCE / OIDC SIWC com validação RS256/JWKS, ACL NTFS `icacls` e streaming `/v1/responses` com `gpt-6-luna`);
    3. `AntigravityTransport` (`antigravity_client.py`, opt-in via CLI `agy`).
  - **Ingestão Remota Privada — Fase 8J (`remote_gateway.py` + `remote_session.py`)**:
    - **Etapa 8J-A (Concluída, evidência sintética)**: Gateway FastAPI isolado em `127.0.0.1:8766` sob `/remote/v1`, desligado por padrão, banco próprio `remote/gateway.sqlite3` (sem mudar o schema v4 do core), exigindo cabeçalho `Tailscale-User-Login` em allowlist, rejeitando `Tailscale-Funnel-Request`, validando `Host` bare + `Origin` HTTPS exato, cookie de sessão + CSRF HMAC-SHA256 (`remote/csrf.key` com ACL `icacls`), prevenção de IDOR por HMAC da identidade e upload com `Content-Length` estrito, limite de bytes, disco livre e idempotência fail-closed (409).
    - **Etapa 8J-1 / Etapa 0 (Gate técnico sintético aprovado pelo coordenador em 2026-10-25)**: `RemoteSessionManager` (`local-transcriber remote-session start|status|stop`), `ProcessVerifier` Win32 64-bit (`wintypes.HANDLE` + timestamp de criação + tokenização exata de `--session-id`), controle seletivo `tailscale serve --https=443` (bloqueando Funnel e preservando configurações de terceiros), trava `.session.lock` e journal transacional persistido antes dos efeitos (`prepared`, `gateway`, `activating`, `active`). Homologação física em hardware/Tailscale/iPad real permanece pendente para a Etapa 8J-B.
    - **Etapa 8J-2 (Concluída, evidência sintética em 2026-10-25)**: Seleção remota de matérias autorizadas via `GET /remote/v1/subjects` direto no `Repository` (sem chamada HTTP ao Core); `allowed_subjects` em `gateway.json` com fallback para `subject_id` legado (singleton) restrito à ausência da chave (rejeitando nulo explícito e lista vazia com ou sem legado), recusa de `allow_all_subjects` e checagem no `lifespan`; seleção por cabeçalho `X-Subject-Id` no upload vinculada ao fingerprint SHA-256 e fail-closed com erro 409 em replays de fingerprints legados (sem apagar claims nem duplicar registros); rate limiting em memória bounded (100 identidades, TTL 300s, relógio monotônico, lock de thread) com resposta 429 e `Retry-After` positivo sem queimar chaves de idempotência (30 tokens leitura com burst 30 / refill 0.5/s; 5 tokens mutação com burst 5 / refill 1/12s).
- **Ferramentas do Agente (`.codex/config.toml`)**:
  - MCPs configurados e validados: `filesystem` (restrito à raiz), `github` separado (`scripts/start-github-mcp.ps1`), `git`, `graphify` (`graphify-out/graph.json`) e `serena` (LSP/Pyright para leitura simbólica cirúrgica).

### Etapa 8J-3 — Upload resumable (implementada em 2026-10-26)

- `POST/GET/PATCH/DELETE /remote/v1/uploads/resumable` e `POST .../{upload_id}/finalize`, com fingerprint dos campos imutáveis, autorização por identidade e os mesmos controles de Host, Origin, Funnel, CSRF e taxa do gateway.
- Sessões, manifesto e metadados de importação somente em `remote/gateway.sqlite3`; chunks sequenciais de 8 MiB (último parcial) no staging, SHA-256, flush/fsync, rename e commit transacional do offset. Schema v4 e endpoint legado preservados.
- Montagem em segundo plano, importação via `MediaLibrary` e enfileiramento opcional na fila existente, sem criar worker de transcrição. Marcador `importing` sem confirmação do Core retorna `409 import_outcome_unknown`; gravação já confirmada permite retomar apenas enfileiramento/conclusão.
- TTL fixo de 24 h, reserva conservadora de disco com sessões ativas, reconciliação no startup, GC a cada 5 min e retenção conservadora de tombstones por pelo menos 7 dias. Evidência sintética: 137 testes no comando focado de gateway/resumable e 473 na suíte completa; homologação física permanece pendente.

### Correções técnicas e Fechamento da Etapa 8J-3 (2026-10-27)

- Correções R1–R8 implementadas após reprovação técnica: semáforo único para montagem/importação, capacidade de uma finalização em execução e duas pendentes; saturação retorna `503 finalization_busy` antes da transição. Reinício reconcilia sessões `assembling` para retomada explícita.
- Limites ativos transacionais: 8 sessões por identidade e 64 globais (`429 active_session_limit_reached`). Expiração, conclusão e aborto liberam capacidade; importações ambíguas preservam a reserva. O upload legado desconta as reservas resumable de `3 * total_bytes` no pré-voo.
- GC isola falhas de I/O por sessão/diretório e tenta novamente no próximo ciclo; falhas SQLite no coletor sinalizam indisponibilidade e bloqueiam endpoints resumable com 503 até um ciclo bem-sucedido.
- Contrato HTTP alinhado para chunks curtos, ENOSPC (507), conflitos e cabeçalhos `Location`/`Retry-After: 2` no finalize 202. GET resumable exige Origin HTTPS e cookie autenticado por HMAC, vinculado à identidade e expiração, sem exigir CSRF na leitura; bootstrap permanece em `/session`.
- Rejeições conhecidas anteriores ao commit do Core (duplicata, mídia inválida, formato/tamanho recusados) terminam em `aborted/media_rejected`, com limpeza e liberação da reserva; falhas potencialmente pós-commit continuam em `import_outcome_unknown`. Replay init reconcilia expiração e retorna 410.
- **Gate técnico da Etapa 8J-3 aprovado e etapa encerrada em 2026-10-27**: **194 testes focados aprovados** (74 resumable + 120 gateway/Etapa 2), Ruff check e format check dos dois arquivos Python, `pip check` e `git diff --check`. Os 473 da suíte completa acima são evidência histórica da implementação inicial; homologação física Tailscale/iPad permanece para a Etapa 8J-B / Etapa 5.

### Etapa 8J-4 — Interface web remota (implementação sintética em 2026-10-27)

- Gateway serve `/`, `/remote`, `/remote/` e `/remote/assets/*` com fronteira Tailscale/Host/loopback e CSP existente. UI isolada em `remote_web/`, incluída em package data; sem dependências de frontend.
- Formulário de matéria/áudio, SHA-256 incremental com fatias de 8 MiB e digest por chunk, upload resumable sequencial, metadados de retomada no navegador, reconciliação de offset, espera em 429/503, acompanhamento de job e leitura/cópia da transcrição.
- GET de status resumable sem `Origin` permitido somente para ID exato, cookie e CSRF válidos, `Sec-Fetch-Site: same-origin` e `Sec-Fetch-Mode: cors`; demais métodos/rotas preservam a exigência anterior.
- Evidência sintética: 221 testes focados aprovados (27 da interface e 194 regressões do gateway/resumable/Etapa 2), Ruff check/format, `pip check` e `git diff --check` aprovados. Wheel sintético mínimo construído e instalado em diretório isolado com os cinco assets. Safari/iPad físico, cabeçalhos produzidos pelo WebKit e tailnet externa permanecem para a Etapa 5.

## Próximo Passo Permitido (Depende de Autorização Explícita)

- **Fase 8J — Etapa 5**: homologação física em Safari/iPad e tailnet externa, incluindo retomada após fechamento da aba, segurança de headers e leitura real da transcrição. Gate técnico sintético da Etapa 4 revisado e aprovado pelo coordenador em 2026-10-27.
