# Arquitetura técnica viva (`Local Transcriber`)

> Visão arquitetural enxuta da versão `0.7.1` (schema SQLite `v4`). O histórico narrativo detalhado das fases 1 a 8I encontra-se arquivado em `docs/archive/pre-slim-2026-10-25/FOUNDATION.md`.

## 1. Estrutura e Módulos (`src/local_transcriber/`)

- `config.py`: resolve `AppConfig` e `RuntimePaths` (`%LOCALAPPDATA%\LocalTranscriber` por padrão, ou `LOCAL_TRANSCRIBER_DATA_DIR`), confinando caminhos relativos (`media/`, `exports/`, `models/`, `auth/`, `remote/`) e rejeitando traversal (`..`), barras invertidas ou caminhos absolutos.
- `models.py` / `exceptions.py`: dataclasses imutáveis de domínio (`Subject`, `Recording`, `TranscriptionJob`, `JobPhase`, `JobEvent`, `Transcript`, `Segment`, `Word`, `ExportedArtifact`) e exceções tipadas (incluindo `LeaseOwnershipLost`).
- `database.py` / `repository.py`: SQLite com migrações incrementais imutáveis (v1→v4), chaves estrangeiras ativas, consultas 100% parametrizadas e busca textual FTS5 sincronizada por triggers.
- `media.py`: importação atômica via `media/.incoming` com cálculo de SHA-256 em streaming, validação real de contêiner/áudio via PyAV/FFmpeg e recusa de exclusão de gravações com job `pending` ou `running`.
- `exporters.py`: renderizadores determinísticos UTF-8 (`LF`) para `TXT`, `MD`, `SRT`, `VTT` e `JSON` sob `exports/`.
- `models_manager.py` / `transcription.py`: `ModelManager` (sem rede em list/check; download apenas via CLI `--confirm`) e `FasterWhisperEngine` (`local_files_only=True`, perfis `cpu` `int8`, `cuda` `int8_float16` registrando DLLs padrão NVIDIA via `os.add_dll_directory` apenas no processo atual, e `auto`).
- `queueing.py`: fila SQLite persistente e worker sequencial único. Faz pré-consulta readonly antes de `BEGIN IMMEDIATE` (evitando contenção em fila vazia), compare-and-set de status, renovação de lease por heartbeat com retries transitórios limitados e publicação transacional única (`Transcript` + `succeeded`).
- `api.py` / `web/`: Core API FastAPI restrita a `127.0.0.1:8765` (`--workers 1` com lock de processo), validação de `Host`/`Origin` local, streaming de mídia com `Range` (206/416), SSE incremental por cursor (`last_event_sequence` / `Last-Event-ID`) e SPA vanilla offline sem `innerHTML`/CDN, com controle monotônico de requisições (`async_state.js`).
- `summarizer.py` / `chatgpt_auth.py` / `chatgpt_client.py` / `antigravity_client.py`: pipeline Map-Reduce temporal (blocos de 20 min) gerando sidecars `.resumo.md` e `.resumo.json` (schema `1.0.0`) através da abstração `LLMTransport` (`OllamaTransport` local padrão `qwen2.5:3b`, `ChatGPTTransport` opt-in via OAuth PKCE SIWC `/v1/responses` com `gpt-6-luna` e ACL NTFS `icacls`, e `AntigravityTransport` opt-in via `agy`).
- `remote_gateway.py` (Fase 8J-A): aplicação FastAPI separada (`127.0.0.1:8766`, prefixo `/remote/v1`, desligada por padrão em `remote/gateway.json`), banco isolado `remote/gateway.sqlite3`, cabeçalho obrigatório `Tailscale-User-Login` em allowlist, bloqueio de `Tailscale-Funnel-Request`, validação estrita de `Host` bare e `Origin` HTTPS, cookie de sessão + CSRF HMAC-SHA256 (`remote/csrf.key` com ACL `icacls`), escopo anti-IDOR por identidade e proteção de upload (`Content-Length` obrigatório, limite de bytes, timeout, disco livre e idempotência fail-closed 409).
- `remote_session.py` (Fase 8J-1 / Etapa 0): `RemoteSessionManager` (`remote-session start|status|stop`), `TailscaleCli` (inspeção fail-closed de `serve status`, proibição de Funnel, ativação/desativação seletiva de `tailscale serve --https=443` apenas quando comprovada posse exclusiva do mapping), `ProcessVerifier` Win32 64-bit (`wintypes.HANDLE`, tempo de criação e argumento `--session-id=<uuid>`), serialização por `.session.lock` e journal em disco com `fsync`/`replace` antes de cada efeito.
- `cli.py`: entrypoint unificado `local-transcriber` (`python -m local_transcriber.cli`).

### Upload resumable — Etapa 8J-3

O gateway mantém `remote_resumable_sessions`, `remote_resumable_chunks`, `remote_resumable_metadata` (matéria, título e data) e o registro de migração exclusivamente em `remote/gateway.sqlite3`. O Core continua no schema v4. Arquivos ficam em `remote/incoming/<upload_id>/chunks/`, com nomes derivados somente de IDs e índices do servidor, e recusa de links/reparse points.

O servidor aceita chunks sequenciais nominais de 8 MiB, valida SHA-256 e tamanho, executa flush/fsync e rename antes de avançar o manifesto/offset em `BEGIN IMMEDIATE`. Locks por sessão protegem PATCH, finalização, cancelamento e GC. A montagem em segundo plano concatena o manifesto e valida o hash final; o marcador durável `importing` antecede `MediaLibrary.import_stream`. A confirmação do `recording_id` é persistida antes do enfileiramento opcional pela fila existente; somente então a sessão vira `completed`. Nenhum engine ou worker de transcrição é criado pelo gateway.

No startup, partes sem commit são removidas, chunks commitados são conferidos e montagens interrompidas podem ser refeitas. Importação sem confirmação resulta em `409 import_outcome_unknown`, sem retry automático no Core; com gravação confirmada, finalize pode retomar apenas fila/conclusão. O TTL é fixo em 24 h, a reserva exige `min_free + 3*S + reservas ativas`, o GC roda no startup e a cada 5 min, e tombstones duram pelo menos 7 dias. Sessões `importing` são preservadas para reconciliação.

## 2. Fronteiras e Invariantes Críticas

1. **Isolamento Core vs. Gateway Remoto**: O Core API (`8765`) nunca é exposto na tailnet; o Gateway (`8766`) apenas insere mídias/jobs validados e consulta status/transcrições pertencentes ao `identity_hash` do solicitante, sem alterar o schema SQLite v4 do core.
2. **Transacionalidade e Falha Fechada**: Nenhuma transcrição ou resumo parcial é publicado em caso de erro; perda de lease levanta `LeaseOwnershipLost`; ambiguidade pós-crash em upload remoto retorna `409 Conflict` sanitizado; journal remoto incompleto bloqueia novas mutações até reconciliação explícita.
3. **Privacidade e Zero Rede Implícita**: Nenhum modelo Whisper é baixado sem `--confirm`; nenhum texto de transcrição sai da máquina sem ação opt-in explícita do usuário.
## Interface web remota da Fase 8J-4

O gateway privado em `127.0.0.1:8766` serve o shell em `/`, `/remote` e `/remote/`, e os cinco arquivos de `src/local_transcriber/remote_web/` em `/remote/assets/*`. O mount é isolado da UI local `web/` e não intercepta `/remote/v1`. O middleware de fronteira e os cabeçalhos de segurança existentes cobrem shell e assets; o wheel inclui HTML, CSS e JS de `remote_web/`.

O navegador mantém sessão e CSRF apenas em memória. A retomada após reload persiste somente metadados de upload/job no armazenamento local; bytes de áudio e transcrição não são persistidos. A verificação SHA-256 total precede o init, e cada PATCH usa uma fatia de até 8 MiB com hash próprio.
