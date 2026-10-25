# Fase 8J-A — Gateway Privado FastAPI em Loopback para Ingestão Remota (2026-10-24)

## Contexto e Objetivo

A Etapa 8J-A implementou um gateway HTTP privado e independente, desacoplado da API central do Local Transcriber, concebido para viabilizar o envio seguro de áudios de aulas e consulta de progresso/transcrições a partir de dispositivos móveis do usuário (ex.: iPad) através de um proxy reverso privado de identidade (ex.: Tailscale).

O gateway opera sob a premissa fundamental de segurança por padrão:
- Permanece desativado a menos que explicitamente habilitado em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.json`.
- Vincula-se estritamente ao loopback (`127.0.0.1`), sem abrir portas para a rede física ou pública.
- Não expõe rotas internas, sumarização LLM (Ollama/ChatGPT), documentação interativa (Swagger/ReDoc) ou CORS.
- Requer identificação estrita e autenticada fornecida por um proxy reverso confiável local.
- Opera sob o prefixo controlado `/remote/v1`.

## Arquitetura Implementada

### 1. Separação de Processos e Portas
- Core API: executada na porta `8765`, dedicada à interface web local e operações no computador.
- Remote Gateway: executado por padrão na porta `8766` (configurável via CLI `local-transcriber remote-gateway serve --port`, estritamente em `127.0.0.1`), com Uvicorn configurado com `proxy_headers=False`, `server_header=False` e `access_log=False`.
- Um único worker de transcrição: o gateway apenas enfileira jobs na fila SQLite core (`transcription_jobs`), sendo consumido pelo mesmo worker existente do sistema. Nenhum segundo worker ou engine concorrente é criado.

### 2. Portão de Segurança Gemini 4 Argon e Correções Finais
- **Identidade em Allowlist e Bloqueio de Funnel**:
  - Validação estrita do cabeçalho `Tailscale-User-Login`.
  - Cabeçalho ausente ou vazio resulta em negação com código **401 Unauthorized**.
  - Cabeçalho duplicado ou identidade não autorizada na allowlist resulta em **403 Forbidden**.
  - Requisições contendo `Tailscale-Funnel-Request` são imediatamente rejeitadas com **403 Forbidden**.
- **Proteção CSRF, Host e Origem**:
  - Validação de `Host` exigindo hostname bare exato na allowlist, rejeitando portas, caminhos, queries, fragmentos ou credenciais de usuário (400 Bad Request).
  - Validação de `Origin` exigindo origem HTTPS exata sem barra final (`/`) ou portas inesperadas (403 Forbidden).
  - O endpoint `GET /remote/v1/session` emite um cookie com `session_id` aleatório (`SameSite=Strict`, `HttpOnly`, `Secure`, caminho `/remote/v1`) e um token CSRF com assinatura HMAC-SHA256 vinculada à identidade e à sessão.
  - Segredo de assinatura persistido em `%LOCALAPPDATA%\LocalTranscriber\remote\csrf.key` com ACL restrita do Windows (`icacls`), sendo validado e reaplicado preventivamente no startup mesmo quando preexistente.
- **Isolamento de Estado e Mitigação de IDOR**:
  - Persistência dedicada em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.sqlite3`, preservando o schema v4 do banco core inalterado.
  - Gravações e jobs são indexados pela chave HMAC da identidade, impedindo enumeração e acesso cruzado entre usuários ou a gravações importadas localmente no notebook.
  - Proibição estrita em nível de banco (índice parcial `UNIQUE`) e código de associar um `recording_id` em estado `completed` a uma identidade distinta.
- **Defesa no Streaming, Concorrência e Sanitização**:
  - Exigência mandatória de cabeçalho `Content-Length` válido (rejeitando `Transfer-Encoding: chunked` e ausência com **411 Length Required**).
  - Lock de concorrência assíncrono (`upload_lock`) serializando uploads dentro do processo gateway cobrindo a checagem de disco, recepção de bytes em streaming, pré-checagem de SHA no repositório core, importação e persistência do estado, mitigando concorrência TOCTOU de espaço em disco e colisões internas; concorrência com importações locais simultâneas no core não foi medida em hardware real.
  - Contagem real de bytes recebidos durante o streaming, abortando conexões que excedam o tamanho declarado ou o limite configurado (`max_upload_bytes`) com **413 Content Too Large**.
  - Timeout total da recepção do corpo (`request_timeout_seconds`, padrão 600.0s).
  - Limpeza automática de arquivos parciais órfãos (`.part`) na inicialização e em desconexões/falhas.
  - Captura e sanitização de `DuplicateMediaError` e `sqlite3.IntegrityError` (colisão de SHA-256) retornando **409 Conflict** genérico, sem vazar IDs ou caminhos existentes.
- **Idempotência Transacional e Falha Fechada**:
  - Suporte a cabeçalho `Idempotency-Key` no upload e na criação de jobs.
  - Requisitar um upload cujo estado atual seja `importing` recente retorna **409 Conflict** (busy), impedindo sobreposição.
  - Em retries após crash ou tempo excedido em `importing`, caso a mídia já exista no catálogo core, a requisição falha fechada com **409 Conflict** sanitizado, evitando IDOR (visto que o schema v4 do core não armazena a identidade do gateway para provar a posse retrospectiva sem alteração estrutural).
  - Se a mídia não existir no core após crash, a reivindicação é reiniciada em `receiving` permitindo retry bem-sucedido.
  - Agendamento de job para gravação posteriormente excluída no core resulta em **410 Gone**, liberando a claim no bloco `finally`.
- **Privacidade de Logs**: ausência de nomes de arquivos originais, caminhos absolutos, emails, títulos ou transcrições pessoais em logs e respostas de erro.

## Validação e Resultados

### 1. Métricas de Validação Atualizadas
- **Testes do Gateway Remoto**: 83 testes dedicados sintéticos executados em `tests/test_remote_gateway.py`, todos aprovados com 100% de sucesso.
- **Testes do Core do Local Transcriber**: 63 testes principais de regressão executados (`test_api.py`, `test_queue.py`, `test_media.py`, `test_cli.py`), todos aprovados com 100% de sucesso.
- **Ruff Check & Format**: `src/local_transcriber/remote_gateway.py` e `tests/test_remote_gateway.py` 100% em conformidade com as regras do projeto e limites de 100 colunas.
- **Sintaxe e Dependências**: `compileall` e `pip check` aprovados com código de saída 0.
- **Git Diff**: `git diff --check` limpo, sem erros de formatação ou caracteres espúrios.

## Limitações e Portão de Segurança Futuro

1. **Validação Puramente Sintética**: todos os testes foram realizados com mocks determinísticos e em loopback local no ambiente de testes. Não foi configurado nem ativado túnel real Tailscale Serve/Funnel, nem foi feita conexão física com um dispositivo iPad real.
2. **Dependência do Proxy em Produção**: a segurança efetiva contra adulteração de cabeçalhos de identidade em produção dependerá estritamente da correta configuração e isolamento do proxy reverso no host do operador.
3. **Ausência de Interface Web no Gateway**: o gateway destina-se a clientes programáticos (scripts/atalhos do iOS) e não provê interface HTML/JS própria.
4. **Idempotência de Crash Limitada por Schema**: caso o processo sofra crash fatal exatamente entre a importação no core e o registro no banco do gateway, um retry com a mesma chave retornará 409 em vez de 200 replayed, falhando fechado para impedir sequestro de registros (IDOR) entre identidades distintas sem exigir alteração estrutural no schema v4 do core.
5. **Próxima Etapa (8J-B)**: validação física com Tailscale real em hardware de testes dedicado antes de disponibilizar o gateway para uso rotineiro.
