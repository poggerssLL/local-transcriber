# Relatório de Implementação e Evidências da Etapa 2 de Acesso Remoto

**Data:** 2026-10-25
**Autor:** Antigravity (Gemini 3.8 Flash High)
**Status:** Implementação Concluída e Validada Sinteticamente
**Baseline Git Inicial:** Commit `c53695a8d364020a61d75fe3326f3d3686da182d` (Branch `main`, Upstream `origin/main`)
**Contexto de Execução:** Local Transcriber (`C:/Users/erick/OneDrive/Documentos/Local Transcriber`)
**Documentos de Referência:** `AGENTS.md`, `docs/PROJECT_CONTRACT.md`, `docs/PROJECT_STATE.md`, `docs/FOUNDATION.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/KNOWN_ISSUES.md`, `docs/REMOTE_ACCESS_STAGE2_INTEGRATION_PLAN.md`.

---

## 1. Resumo Executivo

1. **O que foi feito:** Implementou-se integralmente a Etapa 2 de Acesso Remoto no módulo `src/local_transcriber/remote_gateway.py` e criou-se a suíte de testes sintéticos determinísticos em `tests/test_remote_gateway_stage2.py` (36 testes, incluindo validação estrita de presença/ausência de `allowed_subjects`, nulo explícito e lista vazia com legado), mantendo 100% de compatibilidade retroativa com os 84 testes preexistentes de `tests/test_remote_gateway.py`.
2. **O que foi encontrado/validado:** A suíte completa passou com **420 testes aprovados** (120 testes específicos do gateway remoto), sem regressão nas camadas de segurança (Loopback, Tailscale Funnel, Host/Origin bare/https, CSRF, IDOR). Os contratos de `allowed_subjects`, singleton fallback para `subject_id` legado restrito à chave ausente (rejeitando nulo explícito e lista vazia), endpoint `GET /remote/v1/subjects` sem vazamento de metadados, validação de `X-Subject-Id` pré-claim/bytes, atrelamento ao fingerprint SHA-256 e rate limiting bounded em memória (30 req/min leitura, 5 req/min mutação, TTL 300s, 100 identidades, 429 com `Retry-After` positivo) foram rigorosamente validados.
3. **O que resta:** A Etapa 2 está concluída no escopo sintético. Permanecem estritamente futuras e dependentes de autorização explícita: a Etapa 3 (protocolo de upload particionado / *resumable chunks*), Etapa 4 (interface web Safari/iPad) e Etapa 5 (homologação física em rede Tailscale real com iPad).

---

## 2. Decisões Arquiteturais e Implementações Técnicas

### 2.1 Configuração e Compatibilidade (`allowed_subjects`)
- Chave `"allowed_subjects"` adicionada ao conjunto estrito `_CONFIG_KEYS`.
- Validação fail-closed: se `allowed_subjects` for omitido em `gateway.json` (chave AUSENTE), o gateway aceita fallback de compatibilidade caso `subject_id` legado esteja configurado com UUID válido (`allowed_subjects = frozenset({subject_id})`).
- Caso `allowed_subjects` esteja presente com valor `null` ou `[]` (lista vazia), o gateway rejeita imediatamente (`RemoteGatewayConfigError: allowed_subjects must be a non-empty list`), mesmo se houver `subject_id` legado configurado.
- Caso ambos estejam ausentes, ou `allowed_subjects` contenha sintaxe não-UUID, o gateway aborta a inicialização levantando `RemoteGatewayConfigError`.
- Caso ambos estejam presentes e válidos, valida-se que `subject_id` pertença obrigatoriamente a `allowed_subjects`, impedindo que a matéria legada burle a allowlist explícita.
- A chave `allow_all_subjects` é categoricamente rejeitada como desconhecida (`unknown keys`).
- No evento `lifespan` do FastAPI, valida-se que **todos** os UUIDs em `allowed_subjects` existam na tabela `subjects` do SQLite local, prevenindo operação com matérias inexistentes.

### 2.2 Endpoint `GET /remote/v1/subjects`
- Rota autenticada (`Tailscale-User-Login`) restrita a loopback e livre de Funnel.
- Acesso direto ao `Repository` local (`repository.list_subjects()`), sem chamadas HTTP nem dependência de rotas no Core API (`127.0.0.1:8765`).
- Filtragem estrita: apenas matérias cujo `id` pertença a `settings.allowed_subjects` são retornadas.
- Modelo de resposta `RemoteSubjectResponse(ApiModel)` expondo **estritamente `id` e `name`**. Metadados como `created_at`, contagem de gravações ou datas são completamente omitidos.

### 2.3 Contrato de Seleção de Matéria em `POST /remote/v1/uploads`
- Extração do cabeçalho `X-Subject-Id`.
- Ordem de precedência:
  1. Se fornecido: valida formato UUID (rejeitando `400 Bad Request`), confere allowlist (rejeitando `403 Forbidden` se não autorizada) e confere existência no SQLite local (rejeitando `422 Unprocessable Entity` se inexistente).
  2. Se omitido: permitido **somente** se houver um singleton autorizado coincidente com o `subject_id` legado padrão configurado; caso `subject_id` seja nulo (mesmo com 1 matéria autorizada) ou haja múltiplas matérias na allowlist, rejeita com `400 Bad Request` exigindo seleção explícita.
- Momento da validação: executada **imediatamente**, antes de invocar `store.claim_upload`, antes de inspecionar disco livre e antes de criar ou receber qualquer byte em arquivos `.part`.
- Incorporação de `resolved_subject_id` no cálculo do fingerprint SHA-256 de upload:
  ```python
  fingerprint = hashlib.sha256(
      json.dumps([filename, title, lesson_date.isoformat(), expected_bytes, content_type.lower(), resolved_subject_id], ensure_ascii=False).encode("utf-8")
  ).hexdigest()
  ```
- Tratamento fail-closed de fingerprints legados: requisições retransmitidas com a mesma chave contra claims antigos de 5 elementos são recusadas com status **`409 Conflict`** (`"legacy upload fingerprint requires a new Idempotency-Key"`), sem deletar o claim do banco de estado (`remote_uploads`) e sem reinterpretar posse ou duplicar áudios na biblioteca.
- Concorrência de exclusão: caso uma matéria seja excluída pelo operador no notebook durante o streaming de áudio, o gateway captura a violação de chave estrangeira ou ausência no catálogo e responde com status **`422 Unprocessable Entity`**, limpando arquivos temporários e liberando o claim.

### 2.4 Rate Limiting Bounded em Memória
- Implementação da classe `InMemoryRateLimiter` operando com algoritmo de *Token Bucket*.
- Indexação estrita pelo HMAC da identidade (`identity_hash`), sem persistir logins em texto puro.
- Relógio monotônico (`time.monotonic`), com suporte a relógio injetável para testes determinísticos.
- Trava de exclusão mútua (`threading.Lock()`) garantindo thread-safety no servidor ASGI.
- Limite de capacidade finita (*bounded memory*): máximo de 100 identidades ativas rastreadas simultaneamente.
- TTL de inatividade de 300 segundos (5 minutos); identidades sem requisições por mais de 5 minutos são purgadas automaticamente.
- Política fail-closed na saturação: se 100 identidades estiverem ativas e uma 101ª tentar registrar tráfego sem avanço de TTL, retorna `429 Too Many Requests` com cabeçalho `Retry-After` positivo, impedindo crescimento descontrolado de heap.
- Pré-condição de autenticação: o rate limiter atua no middleware após validação de Loopback, Funnel, Host, identidade autorizada e CSRF. Requisições não autenticadas ou rejeitadas **nunca alocam bucket em memória**.
- Cotas estabelecidas:
  - **Grupo A (Leitura e Consulta — `/session`, `/subjects`, `/health`, `/jobs/{id}`, `/transcript`):** Balde de 30 tokens (burst até 30 requisições imediatas), reposição contínua de 0.5 tokens/segundo (30 req/min).
  - **Grupo B (Mutações e Recursos — `/uploads`, `/jobs`):** Balde de 5 tokens (burst até 5 requisições imediatas), reposição de 1 token a cada 12 segundos (~0.0833 tokens/s, totalizando 5 req/min).
- Efeito sobre `Idempotency-Key`: como a rejeição 429 ocorre no middleware antes da camada de handlers, **a chave de idempotência não é queimada**. O cliente pode aguardar o intervalo do cabeçalho `Retry-After` e reenviar com a mesma chave.

---

## 3. Matriz de Evidências e Testes de Validação

### 3.1 Comandos Executados e Resultados Fatuais

1. **Testes do Gateway Remoto (Etapa 2 + Regressão Etapa 1):**
   ```powershell
   & .venv/Scripts/python.exe -m pytest tests/test_remote_gateway.py tests/test_remote_gateway_stage2.py
   ```
   **Resultado:** `120 passed in 30.54s` (84 testes de regressão + 36 testes da Etapa 2).

2. **Suíte Completa de Testes da Aplicação:**
   ```powershell
   & .venv/Scripts/python.exe -m pytest --basetemp=<unique_tmp>
   ```
   **Resultado:** `420 passed in 76.11s (0:01:16)`.

3. **Validação de Sintaxe e Tipagem:**
   ```powershell
   & .venv/Scripts/python.exe -m py_compile src/local_transcriber/remote_gateway.py
   ```
   **Resultado:** Retorno código 0, sem erros.

4. **Linting e Formatação (Ruff):**
   ```powershell
   & .venv/Scripts/ruff.exe check src/local_transcriber/remote_gateway.py tests/test_remote_gateway.py tests/test_remote_gateway_stage2.py
   & .venv/Scripts/ruff.exe format --check src/local_transcriber/remote_gateway.py tests/test_remote_gateway.py tests/test_remote_gateway_stage2.py
   ```
   **Resultado:** `All checks passed! 3 files already formatted`.

5. **Consistência de Dependências do Ambiente:**
   ```powershell
   & .venv/Scripts/python.exe -m pip check
   ```
   **Resultado:** `No broken requirements found.`

6. **Integridade de Linhas e Diff Git:**
   ```powershell
   git diff --check
   git diff --stat src/local_transcriber/remote_gateway.py tests/test_remote_gateway.py
   ```
   **Resultado:** Retorno código 0, 259 inserções, 17 deleções, escopo estritamente delimitado aos arquivos autorizados.

---

## 4. Escopo de Arquivos e Integridade

### 4.1 Arquivos Modificados / Criados
- `src/local_transcriber/remote_gateway.py`: Implementação de `allowed_subjects`, `RemoteSubjectResponse`, `GET /remote/v1/subjects`, validação de `X-Subject-Id`, fingerprint com matéria, fail-closed de fingerprints legados e `InMemoryRateLimiter`.
- `tests/test_remote_gateway.py`: Ajuste cirúrgico em 3 testes para refletir a passagem de tempo do rate limiting e o 6º elemento do fingerprint em simulação de crash.
- `tests/test_remote_gateway_stage2.py`: Novo arquivo com 33 testes unitários e de integração determinísticos.
- `docs/PROJECT_STATE.md`: Atualização da suíte de 384 para 417 testes e registro factual da Etapa 8J-2.
- `docs/ROADMAP.md`: Transição da Etapa 2 para concluída e fixação da Etapa 3 como próximo passo.
- `docs/REMOTE_ACCESS_STAGE2_INTEGRATION_PLAN.md`: Atualização para status implementado com evidências.
- `docs/PHASE_08J_STAGE2_REMOTE_SUBJECTS_AND_RATE_LIMIT_2026-10-25.md`: Este relatório.

### 4.2 Invariantes Preservados
- Nenhuma alteração em `AGENTS.md` ou alterações locais preexistentes de outras frentes.
- Nenhuma alteração no schema SQLite core (`local_transcriber.sqlite3`, schema v4 imutável).
- Nenhuma dependência externa, modelo baixado silenciosamente ou ativação de rede real.
- Nenhum commit ou push realizado.
