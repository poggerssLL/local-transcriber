# Roadmap (`Local Transcriber`)

> Atualizado em: 2026-10-27. Relatórios detalhados de cada entrega estão em `docs/PHASE_*.md` e o histórico integral anterior em `docs/archive/pre-slim-2026-10-25/ROADMAP.md`.

## Etapas Concluídas

- **Etapas 1 a 7B (MVP Core + CUDA)**: Fundação SQLite v1–v4, biblioteca de mídia PyAV/SHA-256, exportadores determinísticos, Faster Whisper (`cpu` `int8` e `cuda` `int8_float16`), fila persistente com leases/heartbeat, Core API FastAPI (`127.0.0.1:8765`) com SSE incremental, interface web vanilla offline e proteção contra exclusão de gravação com job ativo.
- **Etapas 8 a 8I (Sumarização Estruturada e Qualidade)**: Map-Reduce temporal em `summarizer.py` gerando `.resumo.md`/`.resumo.json` (Ollama local `qwen2.5:3b` padrão + opção opt-in Sign in with ChatGPT `gpt-6-luna` na 8I + cliente Antigravity), instalador e guia para terceiros (8H) e validações sintéticas de fala/qualidade (8F/8G).
- **Etapa 8J-A (Gateway Privado em Loopback)**: Módulo `remote_gateway.py` (`127.0.0.1:8766`, `/remote/v1`, `remote/gateway.sqlite3`), autenticação Tailscale por cabeçalho, CSRF HMAC-SHA256, anti-IDOR e proteção de streaming/idempotência (83 testes dedicados aprovados).
- **Etapa 8J — Etapa 1 e Hardening Etapa 0 (Sessão Privada Temporária)**: Módulo `remote_session.py` (`remote-session start|status|stop`), `ProcessVerifier` Win32 64-bit, orquestração seletiva do Tailscale Serve (Funnel bloqueado), trava `.session.lock` e journal transacional pré-efeito. Gate técnico sintético aprovado pelo coordenador em 2026-10-25 (194 testes focados e 384 na suíte completa aprovados).
- **Etapa 8J — Etapa 2 (Seleção Remota de Matérias e Rate Limiting)**: `GET /remote/v1/subjects` com allowlist em `gateway.json`, compatibilidade transitória com `subject_id` legado restrita à ausência da chave, cabeçalho `X-Subject-Id` validado antes de claims/bytes e atrelado ao fingerprint SHA-256 com fail-closed em replays antigos, e rate limiting bounded em memória por `identity_hash` (30 leitura / 5 mutação, TTL 300s, 100 identidades, 429 com `Retry-After`). 120 testes de gateway e 420 na suíte completa aprovados sinteticamente em 2026-10-25 (com complemento de validação estrita de presença/ausência de `allowed_subjects`).
- **Tooling de Desenvolvimento (2026-10-25)**: MCPs `filesystem`, `github` separado, `git`, `graphify` e `serena` (LSP/Pyright) configurados e validados; documentação enxugada para proteção de *Cached Input*.

---

- **Etapa 8J — Etapa 3 (Upload Resumable + Correções R1–R8 — Concluída e Aprovada Sinteticamente em 2026-10-27)**: Sessões e manifesto isolados em `gateway.sqlite3`, chunks em disco com SHA-256/fsync/rename e offset transacional, montagem em background com semáforo único e fila máxima de 2 pendentes (`503 finalization_busy`), tetos transacionais de 8 sessões ativas por identidade e 64 globais, reserva `3*S` compartilhada com upload legado, GC resiliente (503 se SQLite falhar), cookie autenticado/Origin no GET, rejeições pré-commit terminais (`aborted/media_rejected`), replay init expirado com 410 e recuperação fail-closed (`409 import_outcome_unknown`). Endpoint legado e schema v4 preservados. Gate técnico aprovado pelo coordenador com 194 testes focados (74 resumable + 120 gateway/Etapa 2) e 473 na suíte completa; homologação física permanece para a Etapa 5 (8J-B).

- **Etapa 8J — Etapa 4 (Interface Remota Safari/iPad — Concluída e Aprovada Sinteticamente em 2026-10-27)**: UI privada isolada (`remote_web/`), hash SHA-256 incremental por fatia de 8 MiB, upload/retomada com re-seleção segura, acompanhamento de jobs e transcrição implementados; 221 testes focados aprovados (27 novos e 194 regressões), com wheel sintético mínimo verificado e gate técnico aprovado pelo coordenador.

## Próximas Etapas

1. **Fase 8J-B / Etapa 5 (Gate de Validação Física)**:
   - Validação real ponta a ponta com Tailscale ativo e dispositivo móvel (iPad).
2. **Qualidade Semântica (Complemento 8G) e Etapa 9 (Futuro)**:
   - Refinamento de concisão/atores em resumos longos; futuras frentes de diarização, microfone ao vivo e Home Assistant permanecem fora do escopo atual.
