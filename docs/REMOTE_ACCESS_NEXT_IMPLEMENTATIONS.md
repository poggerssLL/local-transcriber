# Planejamento das Próximas Implementações de Acesso Remoto

**Data:** 2026-10-26
**Baseline:** `0.7.1` (Commit `122d7026dd3a0ef3a9b61ac0b0b74631c0e037c4`)
**Status:** Etapas 0, 1, 2 e 3 Concluídas e Aprovadas Sinteticamente (Etapa 3 encerrada em 2026-10-27); Etapa 4 Autorizada para Planejamento e Implementação
**Documento versionado de referência:** [AGENTS.md](../AGENTS.md).
**Referências locais ainda não publicadas:** `docs/REMOTE_ACCESS_INTEGRATION_PLAN.md` e `docs/PHASE_08J_STAGE1_REMOTE_SESSION_2026-10-25.md`.

---

## 1. Visão Geral, Topologia e Objetivo Proposto

A integração de acesso remoto constitui um **objetivo proposto** para estender o fluxo acadêmico ao iPad. Atualmente, o Remote Gateway opera exclusivamente como backend mínimo em loopback e não serve nenhuma interface web:

1. **Gravação e Disparo (Objetivo Proposto iPad):** Captura de aulas no iPad e upload seguro de áudio diretamente para o notebook através da rede privada e criptografada da tailnet.
2. **Proxy Reverso Privado (Tailscale Serve):** Terminação HTTPS na porta 443 da interface privada Tailscale, autenticação da máquina de origem, injeção de cabeçalhos de identidade e redirecionamento local para `127.0.0.1:8766`.
3. **Gateway Remoto Isolado (`127.0.0.1:8766`):** Aplicação FastAPI restrita a loopback para recepção de mídia, validação de limites e staging temporário. O gateway não possui interface gráfica ativa, não expõe OpenAPI/Swagger e não instancia inferência.
4. **Core API e Invariante de Worker Único (`127.0.0.1:8765`):** Invariante e decisão arquitetural mandatória de manter worker único e sequencial para transcrição com Faster Whisper, consumindo a fila `transcription_jobs` e protegendo CPU/GPU contra concorrência e degradação de recursos.
5. **Persistência Local e Leitura Remota:** Metadados residem no banco SQLite do Core (`local_transcriber.sqlite3`, schema v4 imutável). Como objetivo proposto, a leitura de transcrições será viabilizada via navegador no iPad, sem uso de nuvem pública por padrão e sem Tailscale Funnel.
6. **Separação entre Planos de Controle e de Dados:** O plano de controle (início, auditoria e encerramento de sessão) é estritamente local no notebook via terminal ou launcher. O plano de dados atua apenas na recepção autenticada de mídia e consulta de progresso.
7. **Fronteiras do MVP e Soberania Local:** Microfone ao vivo, diarização e Home Assistant estão fora de escopo. O processamento de áudio é 100% local no notebook; qualquer sumarização em nuvem é estritamente opt-in do usuário.
8. **Autenticação e Governança de Rede:** A segurança combina terminação TLS privada do Tailscale, validação de proxy confiável na tailnet com injeção do cabeçalho `Tailscale-User-Login` e conferência contra a allowlist do operador. Como mecanismo proposto (ainda inexistente no código atual), o rate limiting operará em memória indexado por `identity_hash`. Qualquer requisição contendo o cabeçalho `Tailscale-Funnel-Request` é bloqueada imediatamente com status `403 Forbidden`.

---

## 2. Estado factual atual e gate da Etapa 1

A revisão posterior do hardening exigiu complemento: erros de rede apagavam recuperação,
a ativação precedia a persistência e a extração do primeiro Proxy não provava posse da porta.
O [relatório posterior](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md) registra a correção
local, sem reescrever os relatórios históricos nem tomar sua declaração de sucesso por aprovação.

- Journal antes de spawn e ativação, rollback seletivo e retenção em falhas de rede/disco.
- Inspeção de TCP HTTPS, host, única rota raiz e Proxy exato; estruturas desconhecidas,
  estáticas, TCP forwarding, serviços ou múltiplos handlers/hosts bloqueiam mutações.
- `stop` confirma o resultado do off; limpeza stale usa o mesmo protocolo sem ignorar erros.
- 101 testes de sessão, 8 CLI e 85 gateway (194 focados); suíte completa: 384 aprovados.
  Concorrência usa trava real do SO; HANDLE 64-bit usa callbacks ctypes sintéticos.
- Nenhuma ativação real de Tailscale, rede móvel ou iPad. Gate pendente de revisão independente.

## 3. Complemento da Etapa 1 (Etapa 0) entregue para revisão

Os quatro achados de recuperação/posse e a ausência de testes específicos foram tratados
no código e nos testes. A conferência de aceite pertence ao coordenador; esta entrega
não aprova a si própria nem autoriza Etapa 2.

Limites restantes: journal `prepared` sem PID comprovado, estado corrompido e temporário
sem journal exigem reconciliação manual; configurações desconhecidas de Serve são recusadas.
A trava serializa esta aplicação, sem CAS contra outros clientes Tailscale; não alterar
Serve por outro cliente durante a sessão. Queda de energia não foi homologada.

Próxima ação permitida: revisar o complemento e decidir o gate. Após eventual aprovação,
solicitar nova autorização explícita antes de qualquer implementação da Etapa 2.

---

## 4. Ordem e Especificação das Próximas Etapas

As próximas etapas constituem **propostas técnicas pendentes de revisão e autorização** e devem seguir rigorosamente a sequência abaixo, sem antecipação de escopo:

```
[Etapa 0: Complemento Etapa 1] -> [Etapa 2: Entrada Restrita] -> [Etapa 3: Upload Resumable] -> [Etapa 4: UI Safari/iPad] -> [Etapa 5: Gate Real]
```

### Etapa 0: Complemento e Fechamento do Gate da Etapa 1
- **Escopo:** Complemento de recuperação da Etapa 1, com journal anterior aos efeitos, posse integral de Serve, rollback seletivo e regressões determinísticas; entrega atual aguardando revisão independente.
- **Cobertura Exigida:** Testes automatizados cobrindo explicitamente as lacunas apontadas (recusa de metadados nulos em posse, tipagem Win32 de 64 bits, aborto em conflito de proxy prévio, preservação de estado em falha de desligamento e execução correta do CLI via subprocesso).
- **Critério de Aceite:** O gate será considerado atendido somente quando todas as lacunas específicas forem cobertas por testes automatizados com comportamento estritamente *fail-closed*, sem impacto no Core API ou em jobs locais.

### Etapa 2: Entrada Restrita e Governança de Acesso (Concluída Sinteticamente em 2026-10-25)
- **Seleção Remota de Matérias (`GET /remote/v1/subjects`):** Endpoint mínimo que lista **exclusivamente as matérias configuradas na allowlist do operador**, e não todas as cadastradas no sistema. A consulta deve ser feita diretamente via `Repository` local do Core, sem criar acoplamento ou dependência de chamada HTTP ao Core API.
- **Validação de Entrada:** O upload passa a exigir a matéria vinculada, rejeitando requisições sem matéria autorizada com `400 Bad Request` e preservando compatibilidade com o campo `subject_id` legado.
- **Controle de Taxa (*Rate Limiting*):** Mecanismo de limitação de requisições em memória, indexado por `identity_hash` (hash criptográfico de `Tailscale-User-Login`) com limite finito de memória (*bounded*), sem armazenar logins brutos. Retorna status `429 Too Many Requests` e cabeçalho `Retry-After`. Limites numéricos são propostas a calibrar antes da autorização formal.
- **Preservação de Fronteiras e Erros Padronizados:**
  - Requisição sem cabeçalho `Tailscale-User-Login`: retorno `401 Unauthorized`.
  - Requisição contendo `Tailscale-Funnel-Request`: rejeição imediata com `403 Forbidden`.
  - Validação estrita de cabeçalhos `Host` e `Origin` e proteção CSRF.
  - Desativação total de rotas administrativas e documentação interativa (OpenAPI) no gateway.

### Etapa 3: Protocolo de Upload Resumable Real (Especificação Técnica Detalhada)

> **Status:** Concluída e aprovada no gate técnico sintético em `2026-10-27` (implementação inicial em `2026-10-26` + correções R1–R8 em `2026-10-27`). Evidência sintética: 74 testes resumable, 194 testes no par gateway/resumable e 473 na suíte completa aprovados. Homologação física permanece para a Etapa 5 (8J-B). Arquitetura e recuperação documentadas em `FOUNDATION.md` e `DECISIONS.md` (ADR-043).
> **Invariantes Inegociáveis:** Schema Core SQLite `v4` estritamente imutável; banco de estado isolado em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.sqlite3`; chunks e mídia residem exclusivamente no sistema de arquivos sob `%LOCALAPPDATA%\LocalTranscriber\remote\incoming\<upload_id>\` (nenhum BLOB no SQLite); worker de transcrição sequencial único no Core; nenhum request HTTP ao Core API (`127.0.0.1:8765`); preservação integral do endpoint de upload legado `POST /remote/v1/uploads`.

#### 1. Decisões Arquiteturais e Modelo de Operação
1. **Chunks Sequenciais com Tamanho Definido pelo Servidor:**
   - Adotar chunks individuais sequenciais com tamanho nominal configurável no gateway (proposta padrão: 8 MiB, teto configurável de 32 MiB). Somente o último chunk pode ser menor que o tamanho nominal.
   - Cada requisição `PATCH` transporta exatamente um chunk. O offset validado é sempre a quantidade exata de bytes persistidos em disco e commitados no banco SQLite do gateway, nunca o tamanho de arquivo temporário ou presunção em memória.
2. **Separação entre Recepção e Importação:**
   - A finalização do upload é explícita via `POST /remote/v1/uploads/resumable/{upload_id}/finalize`. Separar o término do envio da montagem e importação permite validar o hash SHA-256 consolidado e tolerar reconexões sem retransmitir mídia.
   - Nenhum uso de multipart/form-data, Base64 ou envelopamento JSON para os bytes de áudio: o streaming binário puro (`application/octet-stream`) minimiza sobrecarga de CPU e memória.
3. **TTL Fixo e Durabilidade:**
   - TTL determinístico de 24 horas (`expires_at = created_at + 86400`), sem renovação automática por chamadas `GET` ou `PATCH`. Persistido como epoch UTC em segundos (relógio monotônico é restrito a prazos de execução transitórios em memória).
   - A expiração impede novas recepções e cancela operações reversíveis, mas não interrompe importações atômicas já em andamento no Core.
4. **Governança de Rate Limiting e Capacidade:**
   - Mantidos os limites estritos da Etapa 2 em memória: 30 requisições/min para leitura (`GET`) e 5 requisições/min para mutação (`POST`, `PATCH`, `DELETE`).
   - Com chunks de 8 MiB, o limite de 5 mutações/min estabelece um throughput nominal máximo seguro em torno de 40 MiB/min, prevenindo saturação de I/O em hardware modesto. O cliente deve observar o cabeçalho `Retry-After` em respostas `429 Too Many Requests`.

#### 2. Contratos REST e Endpoints

Todos os endpoints operam sob o prefixo `/remote/v1/uploads/resumable`, exigem cookie `lt_remote_session`, cabeçalho `Tailscale-User-Login` autorizado, validação estrita de `Host` e `Origin` HTTPS exato, bloqueio incondicional de `Tailscale-Funnel-Request` (403 Forbidden) e cabeçalho `x-csrf-token` em todos os métodos mutantes. Respostas incluem `Cache-Control: no-store`.

* **1. Inicialização da Sessão (`POST /remote/v1/uploads/resumable`):**
  * **Headers:** `Idempotency-Key` (obrigatório, 16..128 chars alfanuméricos/hífen/underline, entropia >= 128 bits), `X-Expected-Sha256` (obrigatório, 64 hex minúsculos).
  * **Body JSON (`InitRequest` com `extra="forbid"`):**
    * `filename` (str, 1..255 caracteres normalizados, sem separadores de caminho ou caracteres de controle).
    * `total_bytes` (int positivo estrito <= `max_upload_bytes`).
    * `enqueue` (bool estrito, default `false`).
    * `subject_id` (str opcional, validado contra `allowed_subjects`).
  * **Respostas:**
    * `201 Created` na primeira criação com cabeçalho `Location: /remote/v1/uploads/resumable/{upload_id}` e payload `SessionResponse`.
    * `200 OK` em replay idempotente idêntico (`identity_hash` + `key_hash` + `fingerprint`).
    * `400 Bad Request` se hash, extensão ou parâmetros forem inválidos (`invalid_hash_header`, `invalid_filename`, `invalid_extension`).
    * `409 Conflict` (`idempotency_conflict`) se a mesma chave for reenviada com parâmetros divergentes.
    * `413 Payload Too Large` se `total_bytes` exceder o teto configurado.
    * `429 Too Many Requests` se o limite de sessões ativas por identidade/global for excedido.
    * `507 Insufficient Storage` se a reserva de disco (`min_free_disk_bytes + 3 * total_bytes`) não estiver atendida.

* **2. Consulta de Progresso e Offset (`GET /remote/v1/uploads/resumable/{upload_id}`):**
  * **Headers de Resposta:** `Current-Offset: <bytes>`, `Upload-Expires: <timestamp>`.
  * **Respostas:**
    * `200 OK` com `SessionResponse` para sessões em `uploading`, `assembling`, `importing` ou `completed`.
    * `404 Not Found` indistinguível para IDs inexistentes ou pertencentes a outra identidade.
    * `409 Conflict` (`import_outcome_unknown`) em cenários de ambiguidade de commit, informando offset e necessidade de intervenção local.
    * `410 Gone` (`session_expired` ou `session_aborted`) para sessões terminadas.

* **3. Envio de Chunks (`PATCH /remote/v1/uploads/resumable/{upload_id}`):**
  * **Headers Obrigatórios:**
    * `Content-Type: application/octet-stream`.
    * `Upload-Offset: <inteiro decimal não negativo>`.
    * `Content-Length: <tamanho do chunk>`.
    * `X-Chunk-Sha256: <64 hex minúsculos>`.
    * `x-csrf-token: <token HMAC da sessão>`.
  * **Processamento:** Leitura em buffers limitados (1 MiB), cálculo simultâneo do SHA-256 do chunk, gravação em `.part`, `os.fsync(handle)` e `rename` atômico para `00000000.chunk`. Em seguida, commit SQLite via `BEGIN IMMEDIATE` persistindo o chunk e incrementando `current_offset`.
  * **Respostas:**
    * `204 No Content` com cabeçalhos `Current-Offset` atualizado e `Upload-Expires`.
    * `400 Bad Request` (`invalid_chunk_length`) se o chunk for menor que o nominal antes do final.
    * `409 Conflict` (`offset_conflict`) se `Upload-Offset != current_offset`, devolvendo o cabeçalho `Current-Offset` para reconciliação imediata do cliente.
    * `411 Length Required` se `Content-Length` for omitido.
    * `413 Payload Too Large` se o chunk exceder o tamanho nominal ou ultrapassar os bytes restantes.
    * `422 Unprocessable Content` (`chunk_hash_mismatch`) se o SHA-256 calculado divergir de `X-Chunk-Sha256` (o arquivo `.part` é descartado e o offset permanece inalterado).
    * `507 Insufficient Storage` em caso de `ENOSPC` durante a gravação.

* **4. Finalização e Montagem (`POST /remote/v1/uploads/resumable/{upload_id}/finalize`):**
  * **Headers:** `x-csrf-token`, `X-Expected-Sha256`.
  * **Body:** JSON vazio `{}` (`extra="forbid"`).
  * **Processamento:**
    * Valida `current_offset == total_bytes` e `X-Expected-Sha256 == expected_sha256`. Rejeita com `409 Conflict` (`upload_incomplete` ou `expected_hash_conflict`) se divergente.
    * Transição atômica de `uploading` para `assembling` e despacho de tarefa em background com concorrência estrita 1 (concorrência gerenciada pelo gateway, sem inferência concorrente).
  * **Respostas:**
    * `202 Accepted` com `Location: /remote/v1/uploads/resumable/{upload_id}` e `Retry-After: 2`.
    * `200 OK` com `SessionResponse` quando o processamento já tiver sido finalizado (`completed`).
    * `503 Service Unavailable` (`finalization_busy`) se a fila de tarefas de I/O estiver saturada.

* **5. Cancelamento / Aborto (`DELETE /remote/v1/uploads/resumable/{upload_id}`):**
  * **Headers:** `x-csrf-token`.
  * **Respostas:**
    * `204 No Content`: transição para `aborted` e expurgo dos chunks em disco (válido para `uploading` ou `assembling` cancelável).
    * `409 Conflict` (`cannot_abort_import`) se a sessão já estiver em `importing` ou `completed` (a exclusão via gateway é proibida para proteger mídias já integradas ao Core).
    * `410 Gone` se já estiver expirada.

#### 3. Modelagem de Dados em `gateway.sqlite3`

O banco do Core (`database.sqlite3`, schema v4) **não sofre nenhuma alteração**. O schema de sessões resumable reside exclusivamente em `gateway.sqlite3` gerenciado por `GatewayStateStore`:

```sql
CREATE TABLE IF NOT EXISTS remote_resumable_sessions (
    upload_id TEXT PRIMARY KEY NOT NULL
        CHECK(length(upload_id)=32 AND upload_id NOT GLOB '*[^0-9a-f]*'),
    identity_hash TEXT NOT NULL
        CHECK(length(identity_hash)=64 AND identity_hash NOT GLOB '*[^0-9a-f]*'),
    key_hash TEXT NOT NULL
        CHECK(length(key_hash)=64 AND key_hash NOT GLOB '*[^0-9a-f]*'),
    fingerprint TEXT NOT NULL
        CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^0-9a-f]*'),
    filename TEXT NOT NULL CHECK(length(filename) BETWEEN 1 AND 255),
    media_extension TEXT NOT NULL CHECK(media_extension IN ('.m4a','.aac','.mp3','.wav')),
    total_bytes INTEGER NOT NULL CHECK(typeof(total_bytes)='integer' AND total_bytes>0),
    chunk_bytes INTEGER NOT NULL
        CHECK(typeof(chunk_bytes)='integer' AND chunk_bytes BETWEEN 1 AND 33554432),
    current_offset INTEGER NOT NULL DEFAULT 0
        CHECK(typeof(current_offset)='integer' AND current_offset BETWEEN 0 AND total_bytes),
    expected_sha256 TEXT NOT NULL
        CHECK(length(expected_sha256)=64 AND expected_sha256 NOT GLOB '*[^0-9a-f]*'),
    validated_sha256 TEXT
        CHECK(validated_sha256 IS NULL OR validated_sha256=expected_sha256),
    state TEXT NOT NULL DEFAULT 'uploading'
        CHECK(state IN ('uploading','assembling','importing','completed','aborted','expired')),
    enqueue INTEGER NOT NULL DEFAULT 0 CHECK(enqueue IN (0,1)),
    recording_id TEXT,
    import_started_at INTEGER,
    error_code TEXT,
    created_at INTEGER NOT NULL CHECK(created_at>=0),
    updated_at INTEGER NOT NULL CHECK(updated_at>=created_at),
    expires_at INTEGER NOT NULL CHECK(expires_at=created_at+86400),
    cleanup_completed_at INTEGER,
    UNIQUE(identity_hash, key_hash),
    CHECK(state NOT IN ('assembling','importing','completed') OR current_offset=total_bytes),
    CHECK(state NOT IN ('importing','completed') OR validated_sha256 IS NOT NULL),
    CHECK(state NOT IN ('importing','completed') OR import_started_at IS NOT NULL),
    CHECK(recording_id IS NULL OR state IN ('importing','completed')),
    CHECK(state<>'completed' OR recording_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS remote_resumable_chunks (
    upload_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK(typeof(chunk_index)='integer' AND chunk_index>=0),
    offset_start INTEGER NOT NULL CHECK(typeof(offset_start)='integer' AND offset_start>=0),
    size_bytes INTEGER NOT NULL CHECK(typeof(size_bytes)='integer' AND size_bytes>0),
    sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    committed_at INTEGER NOT NULL CHECK(committed_at>=0),
    PRIMARY KEY(upload_id, chunk_index),
    UNIQUE(upload_id, offset_start),
    FOREIGN KEY(upload_id) REFERENCES remote_resumable_sessions(upload_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_resumable_sessions_gc
    ON remote_resumable_sessions(state, expires_at);
CREATE INDEX IF NOT EXISTS idx_resumable_sessions_identity
    ON remote_resumable_sessions(identity_hash, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_resumable_recording
    ON remote_resumable_sessions(recording_id) WHERE recording_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS remote_gateway_schema_migrations (
    name TEXT PRIMARY KEY NOT NULL,
    applied_at INTEGER NOT NULL CHECK(applied_at>=0)
);
```

#### 4. Máquina de Estados e Resiliência Fail-Closed

```
[uploading] ---> (total_bytes atingido + finalize) ---> [assembling]
    |                                                         |
    +--> [aborted] (via DELETE ou corrupção)                  +--> [importing] (hash final validado)
    |                                                         |        |
    +--> [expired] (TTL 24h sem finalização)                  |        +--> [completed] (Core confirmou)
                                                              |        |
                                                              |        +--> [ambiguous 409] (crash pós-marcador)
                                                              +--> [aborted] (hash divergente)
```

1. **Transições Atômicas e Locks:**
   - Todas as mutações de estado executam `BEGIN IMMEDIATE` e validam `rowcount == 1`.
   - Lock de processo Win32 exclusivo para a instância do gateway impede concorrência de múltiplos processos na mesma pasta `%LOCALAPPDATA%`.
   - Lock por sessão (`upload_id`) serializa requisições `PATCH`, `finalize` e `DELETE`.
2. **Tratamento da Janela de Ambiguidade de Commit:**
   - Antes de invocar a importação física no Core via `Repository`/`MediaLibrary`, o gateway persiste o marcador durável `state = 'importing'`, `import_started_at = <now>` e `validated_sha256`.
   - Caso o processo ou a máquina sofra queda de energia antes de o gateway receber o `recording_id`, o restart **nunca** re-executa a importação no Core automaticamente (o que causaria mídias duplicadas na biblioteca).
   - Em vez disso, o gateway bloqueia a sessão em fail-closed e responde `409 Conflict` (`import_outcome_unknown`) nas consultas subsequentes, exigindo reconciliação administrativa local orientada pelo marcador.

#### 5. Estratégia de I/O em Disco e Montagem

* **Estrutura de Diretórios Sanitizada:**
  ```
  %LOCALAPPDATA%\LocalTranscriber\remote\incoming\<upload_id>\
  ├── chunks\
  │   ├── 00000000.chunk
  │   ├── 00000001.chunk
  │   └── .<nonce>.part
  ├── assembled.part
  └── assembled.<ext>
  ```
* **Validação de Caminhos e Reparse Points:**
  - O caminho do diretório é derivado estritamente do `upload_id` (32 hex) gerado pelo servidor. Nenhum nome de arquivo vindo do cliente é utilizado no sistema de arquivos.
  - Verificação ativa contra *junctions*, symlinks e reparse points no Windows antes de qualquer abertura, movimentação ou deleção de arquivos.
* **Montagem e Validação de SHA-256:**
  - Montagem sequencial baseada no manifesto do banco de dados copiando chunk por chunk para `assembled.part`.
  - O SHA-256 é calculado de forma contínua durante a cópia dos bytes concatenados (concatenar hashes individuais de chunks não gera o hash do arquivo consolidado).
  - Se o digest calculado coincidir exatamente com `expected_sha256`, o arquivo é promovido via `rename` para `assembled.<ext>`, os chunks intermediários são retidos até a confirmação do Core, e a sessão avança para `importing`.
  - Se o digest divergir, o arquivo montado é descartado, a sessão transiciona para `aborted` com erro `final_hash_mismatch` e nada é enviado ao Core.

#### 6. Governança de Recursos e Coleta de Lixo (GC)

1. **Reserva Conservadora de Espaço em Disco (Modelo 3*S):**
   - O pré-vôo modela o pior caso transitório durante o ciclo de vida: `S` bytes de chunks + `S` bytes de arquivo montado + `S` bytes da importação da biblioteca no Core = `3 * total_bytes`.
   - A inicialização da sessão exige `free_disk >= min_free_disk_bytes + 3 * total_bytes + soma_das_reservas_ativas`.
2. **Coleta Periódica de Chunks e Sessões Expiradas:**
   - Rotina periódica em segundo plano (intervalo de 5 min) e na inicialização do serviço.
   - Sessões em `uploading` ou `assembling` cujo `expires_at` tenha vencido são marcadas como `expired` e seus diretórios de staging são purgados com remoção segura.
   - Metadados de tombstones e idempotência de sessões resolvidas são retidos por 7 dias no SQLite antes de expurgo definitivo. Sessões ambíguas não são purgadas automaticamente.

#### 7. Matriz de Testes Automatizados (9 Categorias Determinísticas)

1. **Migração e Schema:** Coexistência com `_STATE_SCHEMA` existente, idempotência de aplicação de `_RESUMABLE_SCHEMA_V1`, integridade de chaves estrangeiras e imutabilidade absoluta do Core SQLite v4.
2. **Contrato HTTP e Segurança:** Validação de cabeçalhos, rejeição de payloads com campos extras, isolamento estrito entre identidades (IDs de terceiros resultam em `404`), verificação de `Host`, `Origin`, CSRF e bloqueio de Funnel.
3. **Recepção de Chunks e Offset:** Chunks sequenciais nominais e chunk final parcial, rejeição de offsets defasados ou adiantados com `409` e cabeçalho `Current-Offset`, hash incorreto de chunk retornando `422`.
4. **Resiliência a Quedas e Checkpoints:** Simulação de interrupção antes e após `fsync`, antes e após `rename` e antes e após commit SQLite; conferência de que o offset anunciado reflete exatamente os bytes persistidos.
5. **Concorrência e Locks:** Tentativas de `PATCH` concorrente na mesma sessão retornando `409 session_busy` sem corrupção; disputa limpa entre finalização, exclusão e rotina de GC.
6. **Montagem e Integridade:** Validação de integridade do arquivo montado, rejeição de arquivos com SHA-256 divergente sem tocar no Core, tratamento assíncrono com resposta `202`.
7. **Janela de Ambiguidade de Commit:** Crash simulado após gravação de `importing` comprovando que o reinício bloqueia retry com `409 import_outcome_unknown` e impede duplicações no Core.
8. **Governança de Disco e GC:** Rejeição de uploads quando o espaço disponível violar o teto `min_free_disk_bytes`, expurgo automático de chunks órfãos após 24h e retenção de tombstones.
9. **Regressão de Sistema:** Verificação de que o endpoint legado `POST /remote/v1/uploads` permanece 100% funcional, nenhum worker concorrente é gerado e nenhum request HTTP é emitido para o Core API.

#### 8. Sequência de Implementação em Lotes de Commits (Futura)

* **Lote 1 — Modelagem, Contratos e Persistência:** DDL `_RESUMABLE_SCHEMA_V1` em `gateway.sqlite3`, migrações determinísticas, models Pydantic (`InitRequest`, `SessionResponse`, `ErrorResponse`).
* **Lote 2 — Inicialização, Consulta e Capacidade:** Endpoints `POST /remote/v1/uploads/resumable` (init) e `GET .../{upload_id}` (offset), reserva lógica de disco e governança de rate limit.
* **Lote 3 — Streaming de Chunks e Checkpoints:** Endpoint `PATCH .../{upload_id}`, gravação particionada em disco, `fsync`, avanço atômico de offset e lock de sessão.
* **Lote 4 — Montagem, Finalização e Core Adapter:** Endpoint `POST .../{upload_id}/finalize`, montagem sequencial, validação de SHA consolidado, transição `importing` durável e integração lógica com `Repository`/`MediaLibrary`.
* **Lote 5 — Cancelamento, Governança e Startup Reconciler:** Endpoint `DELETE`, rotina de GC periódico (24h), retenção de tombstones e limpeza de arquivos incompletos no boot.
* **Lote 6 — Documentação, Suíte de Testes e Fechamento:** Suíte completa de testes unitários e de integração sintética, atualização de `PROJECT_STATE.md`, `ROADMAP.md` e validação de qualidade (Ruff, pip check).

### Etapa 4: Interface Web Safari/iPad (Futura)
- **Escopo Exclusivo de Frontend:** Interface minimalista em HTML, CSS e JavaScript puros servida na mesma origem HTTPS privada pelo próprio gateway, sem bibliotecas pesadas ou CDNs.
- **Acompanhamento de Job vs. Retomada de Upload:**
  - O `localStorage` armazena o `upload_id` e o `job_id`, permitindo recuperar o **status e acompanhar a transcrição do job** mesmo após fechar a aba (sem necessidade de acesso ao arquivo).
  - Devido ao sandbox de segurança do Safari/iOS, o fechamento da aba destrói a referência ao objeto File/Blob em memória. Para **continuar um upload interrompido**, o cliente deve solicitar a re-seleção do **mesmo arquivo** e validar nome, tamanho e hash antes de retomar o envio a partir do offset registrado. Retomada sem intervenção ocorrerá apenas se o arquivo mantiver acesso durável no navegador.
- **Status:** Estritamente futura; nenhuma alteração ou criação de código de interface será realizada nesta etapa.

### Etapa 5: Homologação Integrada e Gate Físico em Rede Real
- **Separação de Evidências:** Manter relatórios e métricas de testes mockados rigorosamente distinguidos de validações em hardware real.
- **Roteiro de Teste Físico em Campo:**
  1. Iniciar Core API no notebook e confirmar worker de transcrição saudável.
  2. Iniciar sessão remota via `local-transcriber remote-session start` e validar URL Tailscale Serve.
  3. Conectar iPad físico à tailnet a partir de rede externa (dados móveis 4G/5G ou Wi-Fi externo).
  4. Acessar gateway via Safari, selecionar matéria autorizada e enviar áudio de teste M4A.
  5. Simular oscilação momentânea de sinal com a aba aberta para validar retomada automática por offset; em teste de fechamento de aba, validar re-seleção segura do mesmo arquivo antes do reinício de envio.
  6. Confirmar transcrição concluída no notebook e leitura do resultado no Safari.
  7. Encerrar sessão remota via CLI e confirmar que o Core API permanece ativo e jobs pendentes intactos.
- **Garantias Obrigatórias:** Operação estritamente local por padrão (sem cloud acidental) e bloqueio incondicional do Tailscale Funnel.

---

## 5. Matriz de Dependências, Riscos e Critérios de Aceite

| Etapa | Dependência Imediata | Evidência Exigida | Critério de Aceite Principal | Estratégia de Reversão |
| :--- | :--- | :--- | :--- | :--- |
| **Etapa 0** | Código local da Etapa 1 | Testes unitários de regressão das lacunas | Fail-closed em posse, serve status estrito, rollback e CLI corrigido | Preservar snapshot/diff prévio e reverter apenas hunks/arquivos da implementação autorizada com revisão e aprovação; nunca reset global |
| **Etapa 2** | Etapa 0 aprovada no Gate 1 | Testes de allowlist e rate limiting | Somente matérias permitidas, bloqueio 429 Retry-After e 403 Funnel | Reversão controlada via configuração/rollback scoped, mantendo segurança e sem desativar rate limit sem fechar o acesso remoto |
| **Etapa 3** | Etapa 2 aprovada no Gate 2 | Testes de upload particionado | Upload resumable tolerante a crash, integridade SHA-256, schema core intacto | Manutenção exclusiva do upload legado (`/uploads`) |
| **Etapa 4** | Etapa 3 aprovada no Gate 3 | Testes visuais e de navegação | Interface web servida em HTTPS privada com recuperação de job | Desativação de arquivos estáticos no gateway |
| **Etapa 5** | Etapas 0 a 4 concluídas | Logs de teste em rede física | Homologação real iPad -> notebook com encerramento limpo | Desligamento seletivo do Tailscale Serve e gateway |

---

## 6. Procedimentos de Recuperação e Reversão

Em caso de falha durante a execução de qualquer das etapas planejadas, as seguintes diretrizes de reversão devem ser aplicadas:

1. **Reversão Operacional de Sessão e Proxy:** A desativação da porta 443 via `tailscale serve --https=443 off` somente deve ser executada após comprovar que o mapping exato na porta 443 pertence à sessão local. Se a configuração estiver alterada, pertencer a terceiro ou o estado for indeterminado, o operador deve parar imediatamente e não executar o comando `off`. Não executar comandos reais de reversão neste momento.
2. **Preservação de Jobs em Andamento:** Falhas na camada de gateway ou na conexão móvel não devem sob hipótese alguma cancelar jobs já inseridos na fila do Core API (`transcription_jobs`), que continuarão a ser processados pelo worker sequencial do notebook.
3. **Recuperação e Quarentena do Banco do Gateway:** Caso haja corrupção ou inconsistência no banco `gateway.sqlite3`, o arquivo não deve ser purgado ou recriado às cegas para não destruir metadados de posse e idempotência. Deve-se planejar cópia protegida fora do Git, quarentena reversível do banco após o encerramento seguro do processo do gateway, diagnóstico consistente e recuperação validada, sem apagar registros nem associar arquivos por inferência. A base central do sistema (`local_transcriber.sqlite3`) permanece integralmente isolada.
4. **Isolamento de Erros e Proteção contra Cascata:** Falhas de rede ou interrupções abruptas do cliente móvel nunca devem comprometer a estabilidade do Core API. O isolamento de processos em portas de loopback distintas (`8765` para o Core e `8766` para o Gateway) garante que nenhum travamento no gateway cause perda de dados de transcrições locais em andamento.
5. **Prevenção de Comandos Destrutivos:** É estritamente vedado executar comandos de reset global como `tailscale down` ou `tailscale serve reset`, os quais desestabilizariam configurações de rede e serviços alheios à aplicação.

---

## 7. Diretrizes de Governança e Regras de Transição

1. **Caráter Puramente Documental:** Este documento formaliza propostas técnicas e o diagnóstico do coordenador. Ele **não autoriza** a execução das etapas planejadas sem nova ordem explícita.
2. **Imutabilidade de Código Existente:** Nenhum arquivo de código, teste ou configuração preexistente foi alterado neste ciclo de trabalho.
3. **Preservação do Histórico de Fases:** Os relatórios de fases concluídas permanecem intactos como evidência factual de suas execuções originais.
4. **Privacidade e Segurança:** Este documento não inclui caminhos absolutos pessoais de diretórios, identificadores efêmeros de runtime, credenciais, chaves ou dados pessoais sensíveis.
5. **Conformidade com AGENTS.md:** O versionamento de dados, áudios, bancos SQLite ou arquivos temporários permanece estritamente proibido.
6. **Autorização para Fases Futuras:** Qualquer alteração de código relativa à Etapa 0 ou às Etapas 2, 3, 4 e 5 requer novo despacho formal emitido pelo coordenador após validação deste documento pelo usuário.
7. **Rastreabilidade de Decisões:** Todas as alterações estruturais futuras deverão ser catalogadas em `docs/DECISIONS.md` antes de sua incorporação ao baseline da aplicação.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.
