# Limitações e Problemas Conhecidos Ativos (`KNOWN_ISSUES.md`)

> Atualizado em: 2026-10-25. Registra apenas limitações atualmente ativas no produto (`v0.7.1`). Registros de manutenções passadas já resolvidas estão em `docs/archive/pre-slim-2026-10-25/KNOWN_ISSUES.md`.

## 1. Core, Mídia, Fila e Interface Local

- **Codecs e Reprodução no Navegador**: A importação aceita contêineres/codecs decodificáveis pelo PyAV instalado (sem conversão/normalização), enquanto a reprodução no player HTML depende dos codecs suportados pelo navegador local.
- **Duplicidade por Bytes (SHA-256)**: Detecta igualdade exata de arquivo, não equivalência acústica/perceptual.
- **Janela entre Filesystem e SQLite em Queda Abrupta**: Exceções normais limpam/compensam arquivos, mas queda abrupta de energia entre escrita em disco e commit SQLite pode exigir reconciliação manual.
- **Execução `At Least Once` e Cancelamento Cooperativo**: O Faster Whisper não possui retomada acústica parcial (jobs recuperados após perda de lease reiniciam a inferência) e o cancelamento/shutdown aguarda o término da chamada indivisível corrente do engine.
- **Pesquisa FTS5 e UI Local**: A busca FTS5 ainda não oferece ranking avançado ou filtros compostos; a seleção aberta na aba de leitura não é codificada na URL ao recarregar a página; `/api/openapi.json` é local (sem Swagger/ReDoc HTML para evitar CDN).

## 2. Transcrição Real e Sumarização (Ollama / ChatGPT SIWC)

- **Qualidade Semântica do Resumo Local (`qwen2.5:3b` — Etapa 8G)**: A transcrição sintética em CPU/CUDA atingiu WER 0,0, mas a síntese com modelo local `3B` ainda pode apresentar redundância entre parágrafos ou ambiguidade de atores na tese central em textos densos, exigindo gabarito independente antes da Etapa 9.
- **Disponibilidade de Modelos e API Responses no ChatGPT (Etapa 8I)**: `ChatGPTTransport` exige que `gpt-6-luna` esteja visível em `/v1/models` na conta do usuário (sem fallback silencioso) e depende de validação por prompt + `_extract_json` para conformidade com `TranscriptSummary` sob `/v1/responses` (`store: false`, `stream: true`).

## 3. Acesso Remoto Privado (Fase 8J — Gateway e Sessão Tailscale)

- **Validação Restrita a Mocks Sintéticos (Pendente Gate Físico 8J-B)**: Os módulos `remote_gateway.py` (8J-A) e `remote_session.py` (8J-1/Etapa 0) possuem 194 testes focados determinísticos aprovados, mas ainda não foram executados com `tailscale.exe` real e dispositivo cliente físico (iPad) na tailnet.
- **Matéria Estática na Etapa 1**: Na Etapa 1, os uploads remotos usam o `subject_id` fixo configurado em `remote/gateway.json`. A seleção dinâmica de matérias (`GET /remote/v1/subjects`) e o *rate limiting* por identidade pertencem à **Etapa 2**.
- **Idempotência Pós-Crash Fail-Closed (409) por Imutabilidade do Schema v4**: Se o processo do gateway sofrer crash exatamente após persistir a mídia no banco core (`v4`) e antes de gravar no `gateway.sqlite3`, o retry com a mesma `Idempotency-Key` falha fechado com `409 Conflict` para impedir IDOR (pois o schema v4 não armazena `identity_hash`).
- **Recuperação Conservadora de Journal e Concorrência Externa no Tailscale Serve**: Um crash entre o spawn do processo e a gravação do PID deixa o journal em `prepared`, bloqueando novos `start/stop` até reconciliação manual. Além disso, a trava `.session.lock` serializa apenas o `Local Transcriber`, não impedindo edições concorrentes feitas diretamente por outros clientes na CLI do Tailscale.
