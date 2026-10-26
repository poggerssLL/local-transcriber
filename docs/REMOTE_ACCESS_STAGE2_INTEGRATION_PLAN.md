# Plano de Integração da Etapa 2 de Acesso Remoto

**Data:** 2026-10-25
**Autor:** Antigravity (Gemini 3.8 Flash High)
**Status:** Implementado e Validado Sinteticamente (420 testes aprovados na suíte completa)
**Baseline Git:** Commit `c53695a8d364020a61d75fe3326f3d3686da182d` (Branch `main`, Upstream `origin/main`)
**Contexto de Execução:** Local Transcriber (`C:/Users/erick/OneDrive/Documentos/Local Transcriber`)
**Documentos de Referência:** `AGENTS.md`, `docs/PROJECT_CONTRACT.md`, `docs/PROJECT_STATE.md`, `docs/FOUNDATION.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/KNOWN_ISSUES.md`, `docs/REMOTE_ACCESS_INTEGRATION_PLAN.md`, `docs/REMOTE_ACCESS_NEXT_IMPLEMENTATIONS.md`, `docs/PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md`.

---

## 1. Visão Geral, Baseline e Esclarecimento Histórico

### 1.1 Objetivo Deste Documento
Este documento formaliza as decisões, especificações e resultados de implementação para a **Etapa 2 de Acesso Remoto** do Local Transcriber. O escopo compreende:
1. Consulta de matérias autorizadas via `GET /remote/v1/subjects`;
2. Contrato rigoroso de configuração e compatibilidade para `allowed_subjects`;
3. Contrato exato de seleção de matéria em `POST /remote/v1/uploads` com proteção idempotente e fail-closed;
4. Mecanismo de rate limiting em memória indexado exclusivamente por `identity_hash`;
5. Preservação integral das fronteiras de segurança consolidadas nas etapas prévias;
6. Matriz de erros, mapeamento de símbolos do código real, observabilidade sanitizada e plano de rollback;
7. Plano e evidências de testes sintéticos determinísticos (36 testes novos, 120 de gateway e 420 na suíte completa);
8. Critérios de aceite atendidos.

> [!NOTE]
> A implementação da Etapa 2 foi concluída e validada em ambiente sintético conforme autorização de Erick. Não há interface web remota (UI) nem protocolo de upload particionado (*resumable/chunks*, reservado para a **Etapa 3**). A homologação em hardware físico (iPad/Tailscale real) permanece reservada para a **Etapa 5**.

### 1.2 Baseline e Esclarecimento Histórico Factual
O sistema opera atualmente sob o seguinte estado factual comprovado:
- **Topologia de Processos:**
  - **Core API (`127.0.0.1:8765`):** Servidor HTTP principal, gerenciador de banco SQLite (`local_transcriber.sqlite3`, schema v4 imutável), catálogo e executor do **worker único sequencial** de transcrição local (`faster-whisper`).
  - **Remote Gateway (`127.0.0.1:8766`):** Aplicação FastAPI mínima e isolada em loopback, criada para receber áudios remotos e enfileirar jobs na fila central sem expor UI, Swagger, OpenAPI ou instanciar inferência concorrente.
  - **Tailscale Serve (Proxy Reverso Seguro):** Termina HTTPS privado na porta 443 da tailnet e faz proxy reverso para `127.0.0.1:8766`, injetando a identidade privada `Tailscale-User-Login`. O uso de Tailscale Funnel é estritamente proibido e bloqueado.
- **Validação Sintética Concluída (Etapa 1 / Etapa 0):**
  - O ciclo de vida de sessão temporária (`remote-session start/status/stop`), journal atômico, verificação de propriedade de processo em 64 bits e inspeção integral de portas do Serve foram validados sinteticamente com **194 testes focados** e **384 testes da suíte completa aprovados** (conforme registrado no relatório histórico `PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md`).
- **Esclarecimento sobre Divergências Documentais Anteriores:**
  - Trechos de documentação prévia que registram a Etapa 1 como "pendente de revisão" refletem registros históricos anteriores à aprovação do gate técnico sintético consolidado pelo coordenador.
  - Tais divergências são inconsistências de redação histórica e **não justificam reabertura da Etapa 1** nem autorizam declarar homologação física real antecipada.
  - A homologação em hardware físico (iPad real via rede móvel/Wi-Fi externo) permanece explicitamente futura (reservada para a **Etapa 5**).
  - A **Etapa 2 NÃO foi implementada**. Não há interface web remota (UI) nem protocolo de upload particionado (*resumable/chunks*, reservado para a **Etapa 3**).

---

## 2. Item 1: Endpoint `GET /remote/v1/subjects`

### 2.1 Especificação e Contrato da Rota
- **Método HTTP:** `GET`
- **Caminho:** `/remote/v1/subjects`
- **Autenticação e Limites:**
  - Requer conexão loopback (`server[0] in LOOPBACK_BINDINGS`).
  - Rejeita cabeçalho `Tailscale-Funnel-Request` com status `403 Forbidden`.
  - Exige cabeçalho `Host` permitido (`settings.allowed_hosts`).
  - Exige identidade válida no cabeçalho `Tailscale-User-Login` (`settings.allowed_identities`), caso contrário retorna `401 Unauthorized` ou `403 Forbidden`.
  - Submetido ao rate limiting de leitura (Grupo A: até 30 req/min por `identity_hash`).
- **Payload de Resposta (JSON):**
  Lista de objetos mínimos contendo estritamente os campos autorizados:
  ```json
  [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Direito Constitucional I"
    },
    {
      "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "name": "Direito Penal Militar"
    }
  ]
  ```

### 2.2 Blindagem de Dados e Acesso Direto via Repository
1. **Acesso Direto ao Repositório Local (Sem Salto HTTP):**
   - O Remote Gateway já possui uma instância de `Repository` vinculada à base SQLite do Core (`Database(paths.database)`), conforme verificado em `src/local_transcriber/remote_gateway.py:680-681`:
     ```python
     database = Database(paths.database)
     repository = Repository(database)
     ```
   - O método real inspecionado no código é `repository.list_subjects() -> list[Subject]` (`src/local_transcriber/repository.py:71-76`), que executa:
     ```sql
     SELECT id, name, created_at FROM subjects ORDER BY name COLLATE NOCASE
     ```
   - A listagem de matérias para o gateway **NÃO fará requisições HTTP à Core API** (`127.0.0.1:8765`), eliminando latência, acoplamento desnecessário e dependência de rotas remotas inexistentes no Core.
2. **Filtragem Estrita por Allowlist:**
   - O endpoint itera sobre `repository.list_subjects()` e inclui **apenas** as matérias cujo `subject.id` conste em `settings.allowed_subjects`.
   - Matérias existentes na base de dados do Core que não estejam na allowlist são completamente omitidas do retorno.
3. **Não-Vazamento de Metadados da Biblioteca:**
   - O modelo de resposta exposto (`RemoteSubjectResponse`) conterá **exclusivamente `id: str` e `name: str`**.
   - Campos como `created_at`, contagem de gravações cadastradas, datas de aulas, caminhos de arquivo ou identificadores de mídia **nunca** serão incluídos no payload.
4. **Imutabilidade e Restrição Somente-Leitura:**
   - O Remote Gateway não implementará rotas `POST`, `PUT`, `PATCH` ou `DELETE` para `/remote/v1/subjects`.
   - Criação, edição, renomeação ou exclusão de matérias são prerrogativas exclusivas do operador local através da interface web do Core API (`127.0.0.1:8765`) ou CLI local.

---

## 3. Item 2: Contrato de Configuração `allowed_subjects` e Compatibilidade

### 3.1 Estrutura em `gateway.json`
O arquivo de configuração do gateway reside em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.json` (gerenciado por `load_remote_config` em `src/local_transcriber/remote_gateway.py:271`).

Formato proposto para a Etapa 2:
```json
{
  "enabled": true,
  "allowed_identities": ["aluno@dominio.tailscale.net"],
  "allowed_hosts": ["notebook-erick.dominio.tailscale.net"],
  "allowed_origins": ["https://notebook-erick.dominio.tailscale.net"],
  "allowed_subjects": [
    "550e8400-e29b-41d4-a716-446655440000",
    "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
  ],
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "model_name": "small",
  "profile": "auto",
  "language": null,
  "max_upload_bytes": 209715200,
  "min_free_disk_bytes": 1073741824,
  "csrf_ttl_seconds": 3600,
  "request_timeout_seconds": 600.0
}
```

### 3.2 Política Determinística Fail-Closed
Para prevenir qualquer brecha de segurança ou ambiguidade em runtime, adota-se a seguinte matriz determinística:

| Cenário de Configuração | Comportamento do Sistema | Exceção / Status | Justificativa de Segurança |
| :--- | :--- | :--- | :--- |
| **`allowed_subjects` ausente, mas `subject_id` legado presente e válido** | Aceito com fallback de compatibilidade: `allowed_subjects = frozenset({subject_id})` | Sucesso no carregamento | Permite migração suave de arquivos legados da Etapa 1 sem quebra imediata. Fallback reservado estritamente à ausência da chave. |
| **`allowed_subjects` ausente e `subject_id` ausente** | Falha fechada na inicialização | `RemoteGatewayConfigError: either allowed_subjects or subject_id must be configured` | O gateway não pode inicializar sem ao menos uma matéria autorizada. |
| **`allowed_subjects: null` (nulo explícito)** | Falha fechada na inicialização (com ou sem `subject_id` presente) | `RemoteGatewayConfigError: allowed_subjects must be a non-empty list` | Presença de chave nula é rejeitada; o contrato reserva o fallback estritamente à ausência da chave no JSON. |
| **`allowed_subjects: []` (lista vazia com ou sem legado)** | Falha fechada na inicialização | `RemoteGatewayConfigError: allowed_subjects must be a non-empty list` | Allowlist vazia bloquearia 100% dos uploads; não há fallback para `subject_id` se a chave estiver presente. |
| **Elemento com UUID malformado em `allowed_subjects`** | Falha fechada na inicialização | `RemoteGatewayConfigError: allowed_subjects contains invalid UUID` | Rejeita strings arbitrárias, caminhos relativos ou injeções de caracteres (`_UUID.fullmatch`). |
| **Allowlist mista (`allowed_subjects` E `subject_id` presentes)** | Validação cruzada estrita: `subject_id` **DEVE** pertencer a `allowed_subjects` | `RemoteGatewayConfigError: legacy subject_id must be included in allowed_subjects` | **Impede que a matéria legada burle a allowlist** definida explicitamente. |
| **Exclusão de `allow_all_subjects`** | Qualquer menção a `allow_all_subjects` em `gateway.json` é rejeitada como chave desconhecida | `RemoteGatewayConfigError: gateway configuration contains unknown keys` | **Exclusão deliberada:** autorizações globais/coringa (*wildcard*) violam o princípio do menor privilégio. |
| **Matéria autorizada ausente no SQLite local no startup** | Verificação no `lifespan`: todos os UUIDs de `allowed_subjects` devem existir em `repository` | `RemoteGatewayConfigError: configured subject '{uuid}' does not exist on notebook` | Impede operação com configuração apontando para entidades inexistentes. |
| **Alteração de configuração em disco durante execução** | O gateway não faz hot-reload de configuração em memória | Invariante mantido | Alterações exigem reinício explícito (`remote-session stop` -> `start`), evitando estados parciais ou condições de corrida. |

---

## 4. Item 3: Contrato de Seleção de Matéria no `POST /uploads` Binário

### 4.1 Cabeçalho de Seleção e Extração
O endpoint `POST /remote/v1/uploads` recebe o áudio bruto como streaming de bytes no corpo da requisição HTTP (`application/octet-stream` ou tipos MIME aceitos em `_CONTENT_TYPES`, ex.: `audio/mp4`, `audio/m4a`, `audio/mpeg`). Portanto, metadados continuam sendo transmitidos exclusivamente via cabeçalhos HTTP.

- **Nome do Cabeçalho:** `X-Subject-Id`
- **Localização:** Cabeçalhos da requisição HTTP.
- **Tipo e Formato:** String ASCII contendo UUID Canônico v4 minúsculo (36 caracteres, correspondente a `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`).

### 4.2 Ordem de Precedência e Fallback Legado
A resolução da matéria para o upload ocorrerá na seguinte ordem estrita:
1. **Se `X-Subject-Id` for fornecido na requisição:**
   - Validação de formato: Se não casar com `_UUID`, retorna `400 Bad Request` ("malformed X-Subject-Id header").
   - Validação de autorização: Se o UUID não estiver em `settings.allowed_subjects`, retorna `403 Forbidden` ("subject is not authorized for remote upload").
   - Validação de existência local: Se `repository.get_subject(subject_id)` retornar `None`, retorna `422 Unprocessable Entity` ("subject does not exist on the notebook").
2. **Se `X-Subject-Id` for omitido na requisição:**
   - Fallback de Matéria Única: Se `settings.subject_id` estiver configurado E `len(settings.allowed_subjects) == 1` E `settings.subject_id in settings.allowed_subjects`, utiliza-se o `settings.subject_id` padrão.
   - Rejeição por Ambiguidade: Se houver mais de uma matéria autorizada em `settings.allowed_subjects` e `X-Subject-Id` não for enviado, o gateway retorna `400 Bad Request` ("X-Subject-Id header is required when multiple subjects are authorized").
3. **Momento da Validação:**
   - A validação da matéria e da autorização ocorre **IMEDIATAMENTE** no início do handler, **ANTES** de chamar `store.claim_upload()`, **ANTES** de verificar espaço em disco e **ANTES** de receber ou gravar qualquer byte em `incoming/*.part`.

### 4.3 Idempotência e Imutabilidade do Vínculo de Matéria
Atualmente, o `fingerprint` de upload em `src/local_transcriber/remote_gateway.py:869-874` é gerado por:
```python
fingerprint = hashlib.sha256(
    json.dumps(
        [filename, title, lesson_date.isoformat(), expected_bytes, content_type.lower()],
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()
```
**Proposta Obrigatória para a Etapa 2:**
O identificador `subject_id` resolvido deve ser incorporado explicitamente ao vetor de fingerprint:
```python
fingerprint = hashlib.sha256(
    json.dumps(
        [filename, title, lesson_date.isoformat(), expected_bytes, content_type.lower(), resolved_subject_id],
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()
```

#### Efeitos Arquiteturais:
- **Tentativa com Matéria Diferente sob a Mesma Chave Idempotente:**
  Se o cliente enviar uma requisição subsequente com a mesma `Idempotency-Key`, mas informando um `X-Subject-Id` diferente:
  1. O novo `fingerprint` divergirá do fingerprint armazenado em `remote_uploads` para aquele `key_hash`.
  2. `store.claim_upload(key_hash, identity_hash, fingerprint)` detecta a divergência e retorna `claim.outcome == "mismatch"`.
  3. O gateway responde imediatamente com **`422 Unprocessable Entity`** ("Idempotency-Key was already used for another request").
  4. O upload existente **nunca é revinculado** a outra matéria e os bytes da nova requisição são sumariamente rejeitados.

### 4.4 Análise de Persistência e Schema do Gateway vs. Core
- **Schema do Core SQLite v4 (`local_transcriber.sqlite3`):**
  - **Estritamente Imutável.** A tabela `recordings` já possui a coluna `subject_id TEXT NOT NULL REFERENCES subjects(id)`. Nenhuma migração no Core é necessária ou permitida.
- **Banco de Estado do Gateway (`remote/gateway.sqlite3`):**
  - A tabela `remote_uploads` atual armazena `(key_hash, identity_hash, fingerprint, state, sha256, recording_id, claimed_at, updated_at)`.
  - **Decisão Proposta:** Não é estritamente necessária uma migração estrutural para a Etapa 2 (`user_version = 1` permanece adequado). Como o `fingerprint` SHA-256 já amarra criptograficamente o `subject_id` ao claim e à `Idempotency-Key`, e o `recording_id` final aponta para a tabela `recordings` no Core (onde `subject_id` está gravado de forma canônica), a integridade é matematicamente garantida sem alterar as colunas de `remote_uploads`.
  - *Alternativa Versionada:* Caso se decida futuramente auditar `subject_id` no próprio banco do gateway sem realizar join com o repositório Core, define-se que a migração será estritamente local ao gateway (`PRAGMA user_version = 2` em `remote_gateway.py`), sem tocar na base principal.

### 4.5 Casos de Borda Operacionais
1. **Matéria Removida do Banco Durante a Transmissão de Upload:**
   - Se o operador local excluir a matéria no notebook enquanto o cliente transmite um arquivo grande de áudio:
   - Os cabeçalhos iniciais foram validados com sucesso. Ao término da transmissão dos bytes, o gateway executa `library.import_stream(..., subject_id=resolved_subject_id)`.
   - A inserção na tabela `recordings` do SQLite violará a chave estrangeira `FOREIGN KEY (subject_id) REFERENCES subjects(id)`, levantando `sqlite3.IntegrityError` (encapsulado em `MediaImportError`).
   - O gateway captura a falha no bloco `except`, chama `store.release_upload(key_hash)`, remove o arquivo temporário `.part` e responde com **`422 Unprocessable Entity`** ("media could not be imported"). Nenhum estado corrompido ou arquivo órfão permanece.
2. **Consulta de Transcrição de Gravação Cujo Subject Foi Posteriormente Removido:**
   - Se um áudio foi importado com sucesso no passado, e posteriormente a matéria foi removida da allowlist de `gateway.json`:
   - A consulta de status do job (`GET /remote/v1/jobs/{job_id}`) e a obtenção de transcrição (`GET /remote/v1/jobs/{job_id}/transcript`) validam a posse através de `store.owns_job(identity_hash, job_id)`.
   - **Comportamento Proposto:** O acesso aos resultados de gravações já concluídas e pertencentes à identidade do aluno **NÃO é bloqueado retrospectivamente**. A allowlist de matérias governa a ingestão de *novas* mídias e a listagem ativa, e não a custódia de transcrições já homologadas e pertencentes àquela identidade.

---

## 5. Item 4: Rate Limiting em Memória por `identity_hash`

### 5.1 Princípios Fundamentais e Privacidade
1. **Indexação Exclusiva por `identity_hash`:**
   - As estruturas de limitação de taxa em memória **NUNCA** armazenarão o login em texto puro (`aluno@dominio.tailscale.net`).
   - A chave dos baldes (*buckets*) é calculada via HMAC-SHA256:
     ```python
     identity_hash = hmac.new(secret, f"identity|{identity}".encode(), hashlib.sha256).hexdigest()
     ```
   - Em caso de despejo de logs de diagnóstico de tráfego, apenas hashes parciais ou contadores agregados são visíveis.
2. **Defesa Contra Ataques de Negação de Serviço por Alocação de Memória:**
   - **Ordenação Crítica no Middleware:** A verificação de rate limit é executada **APÓS** a autenticação rigorosa da identidade (`Tailscale-User-Login`) contra `settings.allowed_identities`.
   - **Garantia:** Requisições não autenticadas ou com identidades não autorizadas recebem `401 Unauthorized` ou `403 Forbidden` imediatamente, **SEM** instanciar nenhum bucket ou consumir memória no rate limiter. Isso impede que um cliente externo não autorizado esgote a tabela de buckets em memória.
3. **Execução Antes do Processamento do Corpo:**
   - Em requisições de mutação (`POST /uploads`), o rate limit é avaliado **ANTES** de consumir qualquer byte do streaming HTTP e antes de criar arquivos temporários em disco.

### 5.2 Arquitetura e Algoritmo do Rate Limiter
- **Algoritmo:** *Token Bucket* (Balde de Fichas) com capacidade máxima e taxa de reposição contínua.
- **Relógio Monotônico:** Utilização estrita de `time.monotonic()` para cálculo de delta temporal, prevenindo saltos decorrentes de sincronização de relógio de parede (NTP), horários de verão ou ajustes manuais do SO.
- **Concorrência e Thread-Safety:** Acesso às tabelas de buckets protegido por `threading.Lock()` (ou trava assíncrona dedicada), garantindo integridade contra chamadas paralelas no ASGI server.
- **Limites Finitos (*Bounded Memory*):**
  - Limite máximo de identidades rastreadas simultaneamente: `MAX_TRACKED_IDENTITIES = 100` (suficiente para um dispositivo móvel/estudante pessoal).
  - Tempo de vida inativo (*Bucket TTL*): 300 segundos (5 minutos). Buckets sem requisições por mais de 5 minutos são descartados durante varreduras de limpeza.
  - **Política Fail-Closed na Saturação:** Se a tabela atingir 100 identidades ativas e um novo `identity_hash` autenticado tentar registrar tráfego, o sistema recusa a alocação e retorna `429 Too Many Requests` com `Retry-After`, impedindo crescimento descontrolado de memória.
- **Escopo de Processo Único:**
  - O rate limiting é puramente em memória no processo do gateway. Reinicializações do gateway zeram os contadores. Não há dependência de Redis ou IPC externo.

### 5.3 Agrupamento de Endpoints e Cotas Propostas

```
                                [Requisição HTTP Recebida]
                                            |
                                            v
                                [Validação de Loopback, Host, Funnel]
                                            |
                                            v
                                [Autenticação Tailscale-User-Login]
                                            |
                           +----------------+----------------+
                           | Não Autorizado / Ausente         | Autorizado
                           v                                 v
                     [401 / 403 Erro]           [Calcula identity_hash]
                 (Sem alocação de bucket)                    |
                                                             v
                                              [Verifica Grupo de Rate Limit]
                                                             |
                           +---------------------------------+---------------------------------+
                           |                                                                   |
                           v                                                                   v
                 [Grupo A: Leitura e Sessão]                                       [Grupo B: Mutação e Criação]
                   - GET /remote/v1/session                                          - POST /remote/v1/uploads
                   - GET /remote/v1/subjects                                         - POST /remote/v1/jobs
                   - GET /remote/v1/jobs/{id}
                   - GET /remote/v1/jobs/{id}/transcript
                   - GET /remote/v1/health
                           |                                                                   |
                Cota: 30 req/min (Burst 30)                                         Cota: 5 req/min (Burst 5)
                Refill: 0.5 tokens/segundo                                          Refill: 0.0833 tokens/segundo
                           |                                                                   |
                           +---------------------------------+---------------------------------+
                                                             |
                                            [Saldo de Tokens Suficiente?]
                                                             |
                                            +----------------+----------------+
                                            | Sim                             | Não
                                            v                                 v
                                    [Consome 1 Token]             [429 Too Many Requests]
                                    [Prossegue para Rota]         [Cabeçalho Retry-After Inteiro]
                                                                  (Sem queimar Idempotency-Key)
```

1. **Grupo A — Leitura, Sessão e Status (`read_query`):**
   - **Endpoints Cobertos:**
     - `GET /remote/v1/session`
     - `GET /remote/v1/subjects`
     - `GET /remote/v1/jobs/{job_id}`
     - `GET /remote/v1/jobs/{job_id}/transcript`
     - `GET /remote/v1/health`
   - **Capacidade do Balde (Burst):** 30 tokens.
   - **Taxa de Reposição (*Refill Rate*):** 0.5 tokens por segundo (30 tokens a cada 60 segundos).
2. **Grupo B — Mutação e Recursos Intensivos (`mutation_resource`):**
   - **Endpoints Cobertos:**
     - `POST /remote/v1/uploads`
     - `POST /remote/v1/jobs`
   - **Capacidade do Balde (Burst):** 5 tokens.
   - **Taxa de Reposição (*Refill Rate*):** 5 tokens por minuto (1 token a cada 12 segundos, ~0.0833 tokens/segundo).

### 5.4 Resposta de Exaustão de Cota e Tratamento de Retentativas
- **Código HTTP:** `429 Too Many Requests`
- **Cabeçalho Obrigatório:** `Retry-After: <segundos_inteiros>`
  - Calculado deterministicamente via `math.ceil((1.0 - tokens_atuais) / taxa_de_reposicao)`.
- **Corpo JSON Sanitizado:** `{"detail": "rate limit exceeded"}`
- **Interação com `Idempotency-Key`:**
  - Como o bloqueio 429 ocorre antes do registro de claims em `store.claim_upload` ou `store.claim_job`, **a `Idempotency-Key` NÃO é consumida ou queimada**.
  - O cliente pode aguardar o intervalo estipulado em `Retry-After` e reenviar a requisição com a **mesma chave de idempotência** com segurança total.

---

## 6. Item 5: Preservação das Fronteiras de Segurança e Invariantes

A implementação da Etapa 2 manterá intocadas todas as seguintes garantias arquiteturais:
1. **Loopback Estrito (`127.0.0.1`):**
   - O gateway rejeita qualquer conexão cujo endereço de escuta não esteja em `LOOPBACK_BINDINGS` (`src/local_transcriber/remote_gateway.py:736-737`).
2. **Bloqueio Incondicional de Tailscale Funnel:**
   - Toda requisição contendo `Tailscale-Funnel-Request` é bloqueada imediatamente com status `403 Forbidden` (`src/local_transcriber/remote_gateway.py:738-739`).
3. **Validação Estrita de Host e Origin:**
   - Host deve ser único, sem porta, sem credenciais e pertencer a `settings.allowed_hosts`.
   - Origin em mutações deve ser estritamente HTTPS e coincidir com `settings.allowed_origins`.
4. **Proteção CSRF HMAC Criptográfica:**
   - Métodos mutantes (`POST`) exigem cookie de sessão assinado (`session_id`) e cabeçalho `X-CSRF-Token` válido e não expirado (`CsrfSigner`), amarrado ao `identity_hash`.
5. **Mitigação Radical de IDOR:**
   - Usuários só consultam jobs ou gravações cujo claim de posse tenha sido registrado para seu próprio `identity_hash` (`store.owns_recording` e `store.owns_job`).
6. **Invariante de Worker Único e CPU/GPU:**
   - O Remote Gateway **nunca instancia** Faster Whisper ou consome a fila de transcrição. A inferência é 100% realizada pelo worker local do Core API (`127.0.0.1:8765`), garantindo ausência de degradação térmica ou concorrência descontrolada no notebook.
7. **Imutabilidade do Schema Core v4:**
   - O arquivo `database.sqlite3` permanece estritamente na versão v4.
8. **Ausência de Documentação Interativa e UI:**
   - `docs_url=None`, `redoc_url=None`, `openapi_url=None` no FastAPI.
   - Nenhuma interface gráfica ou arquivos HTML/CSS/JS são servidos nesta etapa.

---

## 7. Item 6: Matriz de Contrato, Erros, Símbolos e Rollback

### 7.1 Matriz de Erros do Remote Gateway na Etapa 2

| Código HTTP | Motivo / Causa Primária | Cabeçalhos Específicos | Exemplo de Detalhe JSON |
| :--- | :--- | :--- | :--- |
| **`400 Bad Request`** | Host inválido, Content-Length ausente/malformado, `X-Subject-Id` com sintaxe não-UUID, múltiplos subjects configurados sem header | - | `{"detail": "malformed X-Subject-Id header"}` |
| **`401 Unauthorized`** | Cabeçalho `Tailscale-User-Login` ausente | - | `{"detail": "missing remote identity"}` |
| **`403 Forbidden`** | Cabeçalho `Tailscale-Funnel-Request` presente, login fora de `allowed_identities`, Origin inválido/ausente em POST, CSRF inválido ou expirado, `X-Subject-Id` fora de `allowed_subjects` | - | `{"detail": "subject is not authorized for remote upload"}` |
| **`404 Not Found`** | Job não encontrado ou pertencente a outra identidade | - | `{"detail": "job not found"}` |
| **`408 Request Timeout`** | Transmissão de upload excedeu `request_timeout_seconds` | - | `{"detail": "upload timed out"}` |
| **`409 Conflict`** | Upload concorrente em andamento com a mesma chave, áudio já importado no Core (anti-IDOR pós-crash), modelo de transcrição não instalado | - | `{"detail": "an upload with this Idempotency-Key is in progress"}` |
| **`410 Gone`** | Gravação ou job referenciado foi excluído do notebook pelo operador | - | `{"detail": "recording is no longer available on the notebook"}` |
| **`411 Length Required`** | Requisição de upload sem cabeçalho `Content-Length` | - | `{"detail": "Content-Length is required"}` |
| **`413 Payload Too Large`** | Tamanho declarado ou recebido excede `max_upload_bytes` | - | `{"detail": "upload is too large"}` |
| **`415 Unsupported Media`** | Tipo de mídia não suportado ou divergente da extensão | - | `{"detail": "Content-Type does not match a supported media filename"}` |
| **`422 Unprocessable Entity`** | Idempotency-Key reutilizada com payload/subject divergente, matéria inexistente no Core no momento da importação | - | `{"detail": "Idempotency-Key was already used for another request"}` |
| **`429 Too Many Requests`** | Cota de requisições por minuto excedida para o `identity_hash` | `Retry-After: <segundos>` | `{"detail": "rate limit exceeded"}` |
| **`500 Internal Error`** | Erro inesperado do servidor sanitizado | - | `{"detail": "internal server error"}` |
| **`507 Insufficient Storage`**| Espaço livre em disco no notebook inferior a `min_free_disk_bytes` | - | `{"detail": "insufficient free disk space on the notebook"}` |

### 7.2 Arquivos e Símbolos Candidatos à Futura Edição

Todas as modificações necessárias para a Etapa 2 concentram-se estritamente em **dois arquivos existentes**:

1. **`src/local_transcriber/remote_gateway.py`:**
   - `_CONFIG_KEYS`: Adicionar `"allowed_subjects"` ao conjunto imutável de chaves permitidas (linhas 90-105).
   - `RemoteGatewayConfig`:
     - Adicionar campo `allowed_subjects: frozenset[str]` (linha 127).
     - Alterar `subject_id: str | None = None` para permitir coexistência com allowlist.
     - Atualizar método `from_mapping` para implementar a validação determinística de UUIDs e allowlist mista (linhas 139-211).
   - `RemoteSubjectResponse`: Novo modelo Pydantic contendo exclusivamente `id: str` e `name: str`.
   - `InMemoryRateLimiter`: Nova classe para rastreamento de baldes de fichas por `identity_hash` com relógio `time.monotonic()`, TTL de 300s e limite de 100 identidades.
   - `lifespan`: Adicionar validação de presença de todos os itens de `allowed_subjects` em `repository.get_subject(sub_id)` (linhas 704-719).
   - Rota `GET /remote/v1/subjects`: Novo endpoint filtrando `repository.list_subjects()`.
   - Handler `POST /remote/v1/uploads`:
     - Extrair e validar cabeçalho `X-Subject-Id` (linha 850).
     - Incluir `subject_id` resolvido no cálculo de `fingerprint` (linha 869).
     - Passar `subject_id=resolved_subject` para `library.import_stream()` (linha 922).
   - Middleware `enforce_gateway_boundary`:
     - Acionar a verificação do `InMemoryRateLimiter` imediatamente após a confirmação da identidade permitida (`identity_hash`), retornando 429 com `Retry-After` antes do processamento das rotas (linha 771).
2. **`tests/test_remote_gateway.py`:**
   - Adicionar fixtures e casos de testes sintéticos determinísticos cobrindo todas as novas regras da Etapa 2.

### 7.3 Observabilidade Sanitizada
- **Logs Estruturados do Gateway:**
  - Registros de log nunca imprimirão o endereço de email bruto (`Tailscale-User-Login`), títulos pessoais de aulas, transcrições ou nomes originais de arquivos.
  - Eventos de auditoria emitirão identificadores ofuscados:
    - `LOGGER.info("remote subjects listed: count=%d identity_hash=%s", len(subjects), identity_hash[:8])`
    - `LOGGER.warning("remote rate limit exceeded: group=%s identity_hash=%s retry_after=%d", group, identity_hash[:8], retry_after)`
    - `LOGGER.info("remote upload claimed: subject_id=%s key_hash=%s", resolved_subject_id, key_hash[:8])`

### 7.4 Estratégia de Rollback
Caso uma futura implementação da Etapa 2 apresente comportamento instável em homologação sintética:
1. **Rollback de Configuração (Sem alteração de código):**
   - O operador pode reverter `gateway.json` para definir apenas um `subject_id` legado caso a compatibilidade continue ativa.
2. **Rollback de Código Scoped:**
   - Reverter estritamente os hunks aplicados em `src/local_transcriber/remote_gateway.py` e `tests/test_remote_gateway.py` via `git checkout` delimitado nos arquivos.
   - Como o banco de dados do Core (`database.sqlite3`, schema v4) não é modificado, nenhuma migração reversa de banco é requerida.
   - O banco efêmero do gateway (`remote/gateway.sqlite3`) pode ter seu arquivo colocado em quarentena sem afetar a integridade da biblioteca central.

---

## 8. Item 7: Plano de Testes Sintéticos Determinísticos

Para garantir cobertura exaustiva sem depender de serviços externos, rede tailnet física ou hardware do iPad, define-se a seguinte matriz de testes a ser implementada na fase de código:

### 8.1 Matriz de Testes Proposta para a Etapa 2

| Categoria de Teste | Caso de Teste Sintético | Cenário / Entrada | Comportamento Esperado |
| :--- | :--- | :--- | :--- |
| **Configuração & Migração** | `test_config_legacy_subject_id_fallback` | `allowed_subjects` ausente, `subject_id` presente | Carrega com `allowed_subjects = {subject_id}` |
| | `test_config_empty_allowed_subjects_fails` | `"allowed_subjects": []` | Levanta `RemoteGatewayConfigError` |
| | `test_config_invalid_uuid_fails` | `"allowed_subjects": ["not-a-uuid"]` | Levanta `RemoteGatewayConfigError` |
| | `test_config_mixed_subject_id_outside_allowlist_fails` | `subject_id` ausente da lista `allowed_subjects` | Levanta `RemoteGatewayConfigError` |
| | `test_config_startup_fails_if_subject_deleted_from_db` | UUID de `allowed_subjects` não existe na tabela `subjects` | Startup aborta via `lifespan` com erro |
| **Endpoint `/subjects`** | `test_get_subjects_returns_only_allowlisted` | 5 matérias no banco, apenas 2 na allowlist | Retorna 200 com lista contendo exatamente as 2 matérias |
| | `test_get_subjects_payload_schema_leak_free` | Requisição válida autenticada | Verifica ausência estrita de `created_at` e dados de biblioteca |
| | `test_get_subjects_rejects_unauthenticated` | Sem `Tailscale-User-Login` | Retorna 401 |
| | `test_get_subjects_rejects_funnel` | Cabeçalho `Tailscale-Funnel-Request: ?1` | Retorna 403 Forbidden |
| **Upload & Seleção** | `test_upload_with_valid_x_subject_id` | `X-Subject-Id` válido e pertencente à allowlist | Gravação criada vinculada à matéria escolhida (201) |
| | `test_upload_with_unauthorized_x_subject_id` | `X-Subject-Id` existe no banco mas NÃO na allowlist | Retorna 403 Forbidden antes de gravar bytes |
| | `test_upload_with_malformed_x_subject_id` | `X-Subject-Id: ../invalid` | Retorna 400 Bad Request |
| | `test_upload_with_missing_header_multiple_subjects` | 2 matérias na allowlist e cabeçalho ausente | Retorna 400 Bad Request por ambiguidade |
| | `test_upload_with_missing_header_single_legacy_subject` | 1 matéria na allowlist coincidente com `subject_id` | Sucesso com fallback automático na matéria padrão |
| **Idempotência Cruzada** | `test_upload_idempotency_mismatched_subject_fails` | Mesma `Idempotency-Key` reenviada com `X-Subject-Id` distinto | Retorna 422 Unprocessable Entity sem alterar a gravação |
| | `test_upload_idempotency_same_subject_replays` | Mesma `Idempotency-Key` reenviada com o mesmo `X-Subject-Id` | Retorna 200 Replayed com cabeçalho `Idempotent-Replayed` |
| **Resiliência de Matéria** | `test_upload_fails_closed_if_subject_deleted_mid_stream` | Matéria excluída do banco SQLite durante o streaming de áudio | Falha na importação, limpa `.part` e retorna 422 sanitizado |
| | `test_transcription_query_succeeds_even_if_subject_unlisted` | Áudio enviado no passado tem sua matéria removida da allowlist | `GET /jobs/{id}` e `/transcript` continuam respondendo 200 |
| **Rate Limiting** | `test_rate_limit_read_group_burst_and_exhaustion` | 31 requisições imediatas em `/subjects` | Primeiras 30 passam (200), a 31ª retorna 429 com `Retry-After` |
| | `test_rate_limit_mutation_group_burst_and_exhaustion` | 6 requisições de upload ou criação de job | Primeiras 5 passam, a 6ª retorna 429 com `Retry-After` |
| | `test_rate_limit_refill_via_monotonic_clock` | Esgota balde, avança mock clock em 12s | Nova mutação é aceita com sucesso |
| | `test_rate_limit_does_not_consume_idempotency_key` | Disparo bloqueado com 429 | Retry após intervalo com a mesma chave é processado normalmente |
| | `test_rate_limit_bounded_memory_pruning` | Cria buckets e avança clock > 300s | Buckets inativos são purgados da tabela em memória |
| | `test_rate_limit_unauthenticated_does_not_allocate` | Disparos sem login | Rejeitados com 401 sem instanciar buckets |

---

## 9. Item 8: Sequência Futura de Implementação, Critérios e Condição de Parada

### 9.1 Execução da Implementação da Etapa 2
A implementação técnica seguiu rigorosamente os passos isolados:
1. **Passo 1 (Configuração):** Atualizado `RemoteGatewayConfig` em `remote_gateway.py` para parsear e validar `allowed_subjects`, mantendo compatibilidade transitória com `subject_id` legado (singleton fallback) e recusa de `allow_all_subjects`.
2. **Passo 2 (Módulo de Rate Limiting):** Implementada a classe `InMemoryRateLimiter` em `remote_gateway.py` com token bucket por `identity_hash` HMAC, relógio monotônico, trava concorrente, TTL de 300s e limite de 100 identidades.
3. **Passo 3 (Endpoint Subjects):** Implementado modelo `RemoteSubjectResponse` (apenas `id` e `name`) e rota `GET /remote/v1/subjects` consumindo diretamente `repository.list_subjects()`.
4. **Passo 4 (Seleção no Upload e Fingerprint):** Atualizada rota `POST /remote/v1/uploads` para extrair `X-Subject-Id`, validar na allowlist e no banco antes de claims/bytes, incorporar `resolved_subject_id` ao fingerprint SHA-256 e tratar fail-closed em replays antigos de fingerprints legados com erro 409.
5. **Passo 5 (Middleware de Rate Limiting):** Conectado `InMemoryRateLimiter` ao pipeline do middleware `enforce_gateway_boundary` após autenticação e CSRF, retornando 429 com `Retry-After` positivo sem consumir chave de idempotência.
6. **Passo 6 (Suíte de Testes):** Criado `tests/test_remote_gateway_stage2.py` com 36 testes cobrindo exaustivamente a matriz sintética (incluindo diferenciação de presença/ausência, nulo explícito e lista vazia com legado); compatibilidade de `tests/test_remote_gateway.py` (84 testes) preservada, totalizando 120 testes de gateway.
7. **Passo 7 (Validação Integral):** Conferência completa com pytest (420 testes aprovados), `ruff check`, `ruff format --check`, `pip check` e `git diff --check`.
8. **Passo 8 (Atualização Documental):** Atualizados `docs/PROJECT_STATE.md`, `docs/ROADMAP.md` e gerado relatório `docs/PHASE_08J_STAGE2_REMOTE_SUBJECTS_AND_RATE_LIMIT_2026-10-25.md`.

### 9.2 Critérios de Aceite Atendidos
- 100% dos testes sintéticos (420 aprovados na suíte completa).
- Zero regressão nas proteções contra Funnel, Host spoofing, CSRF e loopback.
- Uploads com matérias não autorizadas ou manipuladas bloqueados em fail-closed.
- Reenvio da mesma chave de idempotência com matéria divergente bloqueado com 422.
- Reenvio de claim legado (5 elementos) bloqueado com 409 exigindo nova chave, sem apagar claim nem duplicar gravação.
- Rate limiting com retorno determinístico 429 e `Retry-After` positivo sem queimar chave idempotente.
- Nenhum vazamento de login bruto ou caminhos em logs.
- Schema do Core SQLite v4 absolutamente inalterado.
