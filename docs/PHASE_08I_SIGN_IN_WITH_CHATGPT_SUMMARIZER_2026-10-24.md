# Relatório da Etapa 8I — Resumo Estruturado com Sign in with ChatGPT

- **Data**: 2026-10-24
- **Versão do pacote**: 0.7.1
- **Schema SQLite**: v4
- **Status da etapa**: Concluída (código, testes sintéticos determinísticos e documentação viva)

---

## 1. Contexto e Objetivo

A Etapa 8I implementou a opção de síntese pedagógica estruturada utilizando autorização oficial
"Sign in with ChatGPT" e o plano de assinatura ChatGPT do usuário, mantendo o Ollama local
(`qwen2.5:3b`) como motor de inferência padrão e 100% offline do Local Transcriber.

A funcionalidade foi concebida de forma estritamente opt-in: nenhuma requisição externa de IA é
feita por padrão e o usuário é informado explicitamente antes de qualquer transmissão do texto da
transcrição selecionada para a nuvem da OpenAI.

---

## 2. O que foi Implementado

### 2.1 Desacoplamento do Transporte LLM
- Criada a interface abstrata `LLMTransport` em `src/local_transcriber/summarizer.py`.
- Implementado `OllamaTransport(LLMTransport)`, preservando 100% da compatibilidade com o motor
  local Ollama legado e o método `_call_ollama`.
- Desacoplado `TranscriptSummarizer` para aceitar qualquer `LLMTransport` injetado, mantendo
  `OllamaTransport` como padrão padrão.
- O formato estruturado `TranscriptSummary` (schema 1.0.0) e os artefatos sidecar `.resumo.md` e
  `.resumo.json` permanecem inalterados estruturalmente, adicionando apenas o campo `provider` aos
  metadados de proveniência (`provenance.provider` = `"chatgpt"` ou `"ollama"`).

### 2.2 Autenticação OAuth 2.0 PKCE / OIDC ("Sign in with ChatGPT")
- Implementado em `src/local_transcriber/chatgpt_auth.py`:
  - Geração de par PKCE S256 (`code_verifier` e `code_challenge`, RFC 7636).
  - Geração e validação de `state` e `nonce` criptográficos contra ataques CSRF e replay.
  - Integração com o fluxo oficial de autorização da OpenAI para ferramentas open source
    (`https://auth.openai.com/api/accounts/authorize` com escopos `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`,
    recurso `https://api.openai.com/v1`, e `ext_agent_host_id` persistente).
  - Inscrição inicial dinâmica: recebe e preserva o `client_id` emitido pela OpenAI em arquivo protegido
    `client_id.txt` para reautorizações futuras; rejeita ausência de client_id na primeira inscrição e rejeita
    trocas inesperadas de client_id em reautorizações.
  - Reautorização supervisionada: omite `agent_name_hint` e envia `id_token_hint` da conta salva anteriormente.
  - Validação obrigatória de ID token antes de persistir tokens: decodificação de assinatura
    RS256 via algoritmo modular de chave pública com JWKS obtido de `https://auth.openai.com/.well-known/jwks.json`,
    conferência de `iss` (`https://auth.openai.com`), `aud` (`client_id`), `exp > now`, `nonce` e escopos concedidos.
  - Callback loopback supervisionado via rota `/api/auth/chatgpt/callback`:
    - Restrito estritamente a HTTP em `127.0.0.1` (`localhost` rejeitado conforme especificação SIWC oficial).
    - Validação de `state` obrigatória inclusive em callbacks de erro, com TTL de 10 minutos para autorizações pendentes.
    - Sanitização com `_safe_message` e escape HTML estrito (`html.escape`) de emails e mensagens de erro para prevenir XSS.
    - Proibição de exibição de tokens brutos, payloads sensíveis ou caminhos absolutos do sistema em logs/erros.
  - Armazenamento seguro de tokens:
    - Proteção no Windows com ACLs nativas NTFS (`icacls /inheritance:r /grant:r %USERNAME%:(R,W)`), falhando
      fechado se o acesso restrito do usuário não puder ser assegurado.
    - Permissões POSIX `0600` aplicadas apenas em plataformas POSIX, evitando alegações de segurança indevidas por chmod no Windows.
  - Rotação automática de refresh tokens com persistência segura e atômica em
    `%LOCALAPPDATA%\LocalTranscriber\auth\chatgpt_tokens.json` fora do versionamento Git, incluindo o parâmetro `resource`.
  - Suporte a verificação de status (`GET /api/auth/chatgpt/status`), desconexão/logout
    (`POST /api/auth/chatgpt/logout`), e comandos correspondentes na CLI
    (`local-transcriber auth chatgpt status` e `local-transcriber auth chatgpt logout`).

### 2.3 Cliente e Transporte ChatGPT (`ChatGPTTransport`)
- Implementado em `src/local_transcriber/chatgpt_client.py`:
  - Validação estrita do catálogo de modelos da conta via `GET https://api.openai.com/v1/models`
    com o token OAuth, em conformidade com o contrato oficial SIWC (array `models` contendo objetos com `slug` e `visibility`).
    Exige a presença explícita de `gpt-6-luna`; falha com `ChatGPTModelUnavailableError` sem substituição silenciosa de modelo caso ausente.
  - Endpoint de status não informa `has_luna=True` quando a consulta ao catálogo falha por erro de rede ou serviço.
  - Execução de inferência exclusivamente via endpoint `POST https://api.openai.com/v1/responses`
    com payload compatível com planos em preview:
    `model: "gpt-6-luna"`, `reasoning: {"effort": "low"}`, `store: false`, `stream: true`, e texto
    completo da transcrição/chunk no input.
  - Consumo completo de Server-Sent Events (SSE) via evento oficial `response.output_text.delta` (com retrocompatibilidade
    a `response.text.delta`) até o evento terminal `response.completed`.
  - Prevenção estrita de duplicação textual: eventos posteriores `response.output_item.done` e `response.completed`
    não concatenam texto novamente quando os deltas incrementais já foram acumulados.
  - Tratamento determinístico de eventos de erro `response.failed`, `response.incomplete`, `error` e
    códigos HTTP 401, 403, 429 e 503 com exceções de domínio tipadas.
  - Rejeição estrita de fallbacks automáticos para Ollama e recusa de persistência de resumos
    parciais ou corrompidos.

### 2.4 Interface Web Local Vanilla e CLI
- **Web UI** (`src/local_transcriber/web/`):
  - Inclusão de seletor de provedor (`Ollama (Local)` vs `ChatGPT (Plano na Nuvem)`).
  - Barra de status de conexão com identificação de conta conectada e botões de Conectar / Desconectar.
  - Aviso visual e explícito de consentimento antes do envio: informa claramente que o texto da
    transcrição selecionada será transmitido aos servidores da OpenAI.
  - Preservação da arquitetura vanilla: zero dependências de build, CDN ou pacotes npm externos.
- **CLI** (`src/local_transcriber/cli.py`):
  - Adicionado `--provider {ollama, chatgpt}` ao comando `summarize`.
  - Comandos dedicados `local-transcriber auth chatgpt status` e `local-transcriber auth chatgpt logout`.

---

## 3. Validação e Testes

A etapa foi validada estritamente com testes unitários e de integração determinísticos e fixtures
sintéticas. **Nenhuma chamada de rede real à OpenAI ou ao Ollama foi executada nos testes**, e nenhuma
credencial de usuário ou dado de áudio foi persistido.

### 3.1 Novos Testes Automatizados (36 novos testes)
1. `tests/test_chatgpt_auth.py` (16 testes):
   - Geração PKCE RFC 7636 (verifier e challenge SHA-256).
   - Construção de authorization URL com state, nonce, escopos oficiais (`openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`) e parâmetro `resource`.
   - Comportamento de primeira inscrição (`agent_name_hint`) vs reautorização (omissão de `agent_name_hint` e passagem de `id_token_hint`).
   - Persistência e expiração em `ChatGPTTokenStore`, preservando o identificador `client_id.txt` mesmo após `clear()`.
   - Proteção de ACLs no Windows via `icacls` (falha fechada quando usuário indefinido) e permissões POSIX restritas.
   - Validação criptográfica de ID token RS256/JWKS (emissão, audiência, expiração, nonce e assinatura).
   - Troca de authorization code com ID token obrigatório, escopos mandatórios e preservação do issued `client_id`.
   - Rejeição de ausência de ID token, escopos incompletos, ausência de client_id na primeira inscrição e troca inesperada em reautorização.
   - Refresh de token com inclusão de `resource: https://api.openai.com/v1` e rotação de credenciais.
   - Logout e remoção limpa do arquivo de sessão de tokens.
2. `tests/test_chatgpt_transport.py` (7 testes):
   - Verificação de presença de `gpt-6-luna` no catálogo via `/v1/models` com fixture oficial SIWC (`models` contendo `slug` e `visibility`).
   - Rejeição e erro tipado quando `gpt-6-luna` está ausente do catálogo da conta.
   - Consumo SSE bem-sucedido via evento oficial `response.output_text.delta` até `response.completed`.
   - Prevenção estrita de duplicação textual quando `response.output_item.done` e `response.completed` chegam após deltas.
   - Rejeição de streaming com `response.failed`, `error` e `response.incomplete`.
   - Tratamento de erros HTTP 401, 403, 429 e 503 com exceções de domínio tipadas.
3. `tests/test_summarizer_transport.py` (3 testes):
   - `TranscriptSummarizer` executando Map-Reduce completo com transporte injetado.
   - Registro de proveniência (`provider="chatgpt"`, modelo `"gpt-6-luna"`) em metadados e frontmatter.
   - Retrocompatibilidade estrita do `OllamaTransport` com fixtures legadas.
4. `tests/test_api_chatgpt_summary.py` (10 testes):
   - `GET /api/auth/chatgpt/status` (desconectado, conectado e verificação de que falhas no catálogo nunca reportam `has_luna=True`).
   - `GET /api/auth/chatgpt/login` gerando URL válida e registrando estado pendente com TTL.
   - Restrição estrita de `redirect_uri` a loopback HTTP `127.0.0.1` (rejeitando `localhost` e hosts externos).
   - Validação obrigatória de `state` no callback, inclusive em retornos de erro do IdP.
   - Expiração de autorização pendente por TTL (> 10 minutos).
   - Proteção estrita contra XSS via escape HTML (`html.escape`) no callback (erros e display de email).
   - `GET /api/auth/chatgpt/callback` com troca de código e salvamento de tokens.
   - `POST /api/auth/chatgpt/logout`.
   - `POST /api/transcripts/{id}/summary` com `provider="chatgpt"` conectado.
   - `POST /api/transcripts/{id}/summary` rejeitando com 401 quando não autenticado.

### 3.2 Execução da Suíte Completa
- `pytest`: **186 passed** em 26.78s (150 baseline + 36 novos).
- `ruff check .`: **All checks passed!** (0 erros).
- `ruff format --check .`: **72 files already formatted** (0 arquivos divergentes).
- `python -m compileall src tests`: **Compilação de sintaxe 100% limpa** (código de saída 0).
- `node --check src/local_transcriber/web/*.js`: **Sintaxe JavaScript 100% limpa** (código de saída 0).
- `python -m pip check`: **No broken requirements found.**
- `git diff --check`: **Sem conflitos ou erros de whitespace.**

---

## 4. Separação Factual: Mocks vs Execução Real

| Dimensão | Situação na Etapa 8I |
|---|---|
| Autenticação OAuth 2.0 PKCE | Validada deterministicamente com mocks e chaves RSA sintéticas |
| Login real de usuário no navegador | **Pendente** (não autorizado nesta tarefa; sem credenciais) |
| Consulta `/v1/models` | Validada via mock SSE/HTTP |
| Inferência real `gpt-6-luna` | **Pendente** (não acionada; zero consumo de tokens de plano) |
| Streaming `/v1/responses` | Validado via iterador SSE sintético (`response.completed`) |
| Persistência e sidecars | Validado com geração real de arquivos temporários sintéticos |
| Operação offline padrão | Preservada integralmente com Ollama padrão |

---

## 5. Limitações Conhecidas e Próximos Passos

1. **Catálogo de Modelos da Conta**: A inferência requer expressamente a presença de `gpt-6-luna`
   na listagem da conta conectada. Contas sem acesso a esse modelo receberão recusa clara sem
   substituição silenciosa.
2. **Preview da Responses API**: O endpoint `/v1/responses` em modo de compartilhamento de tokens de
   plano exige `store: false` e `stream: true`, e validação JSON local estrita via prompt engineering
   e `_extract_json`.
3. **Próxima Etapa**: Diarização de locutores e transcrição contínua em tempo real (fora do MVP atual).
