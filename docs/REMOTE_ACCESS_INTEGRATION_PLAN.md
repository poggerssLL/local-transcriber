# Plano de Integração e Arquitetura de Acesso Remoto (Etapas 1 a 3)

**Data:** 2026-10-25  
**Baseline:** `0.7.1` (Schema SQLite Core v4 imutável)  
**Status:** Etapa 1/Etapa 0 com complemento de recuperação local, aguardando revisão independente; Etapas 2 e 3 propostas, sem autorização de implementação.  

---

## 1. Visão Geral e Motivação

O **Local Transcriber** foi concebido para catalogar gravações e executar o ciclo de vida completo de transcrições em hardware local, com total soberania de dados. A demanda operacional de registrar aulas e palestras diretamente de dispositivos móveis do usuário (ex.: iPad) exige um mecanismo de ingestão remota seguro, que permita o envio de áudio e acompanhamento de progresso sem expor a máquina à internet pública nem desestabilizar o pipeline local.

Para preservar as garantias do produto, o acesso remoto é estruturado em três etapas complementares e estritamente delimitadas:
- **Etapa 1 (complementada, aguardando revisão):** Ciclo de vida de sessão temporária controlada por CLI/launcher local, journal recuperável antes dos efeitos, inspeção integral da porta Serve, posse fail-closed 64-bit, trava concorrente e entrypoint modular.
- **Etapa 2 (futura, requer nova autorização):** Seleção remota de matérias autorizadas, limitação de taxa (*rate limiting*) e preservação das barreiras de segurança (Host, Origin, CSRF, sem rotas de administração).
- **Etapa 3 (Worker subsequente):** Protocolo de upload particionado (*chunked/resumable*) com verificação de offset, integridade SHA-256, expiração de partes e banco de estado isolado no gateway (`gateway.sqlite3`), mantendo o schema v4 do core imutável.

---

## 2. Invariantes Arquiteturais e Fronteiras de Segurança

Toda a arquitetura de acesso remoto obedece aos seguintes princípios inegociáveis:

1. **Separação Estrita de Processos e Portas em Loopback:**
   - **Core API (`127.0.0.1:8765`):** Executa a API principal, a interface web local e o **único worker** sequencial de transcrição que consome a fila persistente (`transcription_jobs`).
   - **Remote Gateway (`127.0.0.1:8766`):** Aplicação FastAPI independente e mínima, vinculada exclusivamente a `127.0.0.1`. Não expõe documentação interativa (Swagger/ReDoc), sumarizadores LLM, rotas administrativas, arquivos estáticos ou interface web.
   - **Tailscale Serve (Proxy Reverso Seguro):** Termina HTTPS na porta 443 da interface privada Tailscale, valida e injeta o cabeçalho de identidade `Tailscale-User-Login`, e encaminha requisições estritamente para `127.0.0.1:8766`.
2. **Worker Único e Fila Central:**
   - O Remote Gateway **nunca** instancia um worker de transcrição ou motor de inferência concorrente.
   - As gravações recebidas remotamente são enfileiradas diretamente na tabela core `transcription_jobs` e processadas pelo worker do Core API.
3. **Imutabilidade do Schema Core v4:**
   - O banco central `%LOCALAPPDATA%\LocalTranscriber\database.sqlite3` permanece estritamente na versão v4.
   - Qualquer metadado específico do gateway (sessões remotas, chaves de idempotência de upload, estado de chunks) reside em banco isolado `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.sqlite3`.
4. **Tailscale Serve vs. Tailscale Funnel:**
   - O uso de **Tailscale Funnel é terminantemente proibido**. Apenas nós autorizados na tailnet privada do usuário podem alcançar a porta remota.
   - O gateway rejeita ativamente requisições que contenham o cabeçalho `Tailscale-Funnel-Request` com **403 Forbidden**.
5. **Plano de Controle Estritamente Local:**
   - O gerenciamento de sessões (`remote-session start/status/stop`) é acessível apenas localmente no notebook via terminal ou launcher. O gateway não expõe endpoints para iniciar, pausar ou desligar sessões ou serviços.
6. **Desligamento Seletivo e Preservação de Serviços:**
   - Ao encerrar a sessão remota, apenas o proxy do Tailscale Serve mapeado para o gateway e o processo do gateway pertencentes à sessão são finalizados.
   - É **proibido** executar comandos destrutivos globais como `tailscale serve reset` ou `tailscale down`.
   - O Core API e todos os jobs na fila continuam operando normalmente.
7. **Falha Fechada e Prova de Propriedade de Processo:**
   - O encerramento de processos via CLI nunca mata cegamente um PID persistido em disco sem verificar que a linha de comando e a data/hora de criação do processo pertencem inequivocamente ao runtime do Local Transcriber. Em caso de dúvida ou conflito, a operação falha de forma fechada.
8. **Privacidade de Credenciais e Logs:**
   - Nenhuma credencial, cookie, token CSRF, chave secreta ou log bruto contendo transcrições ou títulos pessoais é versionado no repositório.

```
       [Dispositivo Móvel / iPad]
                   |
     (HTTPS via Tailnet Privada)
                   v
     [Tailscale Serve (HTTPS :443)]  <-- Injeta Tailscale-User-Login
                   |
      (HTTP Loopback 127.0.0.1:8766)
                   v
     [Remote Gateway (FastAPI)]      <-- Valida Allowlist, CSRF, Host/Origin
          |                  |
   (Chunks/Uploads)   (Enqueue Jobs)
          v                  v
 [gateway.sqlite3]   [Core SQLite v4] <--- [Core API / Web UI :8765]
                             ^
                             | (Consome Fila)
                     [Worker Único]
```

---

## 3. Detalhamento das Etapas e Roadmap

### Etapa 1 — Ciclo de Vida da Sessão Temporária e Orquestração (Escopo Atual)

- **Objetivo:** Permitir que o operador inicie e encerre uma sessão privada temporária com um único comando na CLI ou launcher PowerShell, exibindo a URL HTTPS correspondente e garantindo reversão limpa.
- **Módulos e Comandos:**
  - `src/local_transcriber/remote_session.py`: gerenciador de ciclo de vida (`RemoteSessionManager`), cliente Tailscale CLI (`TailscaleCli`) e verificador de processo (`ProcessVerifier`).
  - CLI:
    - `local-transcriber remote-session start [--port 8766] [--https-port 443] [--background] [--timeout 30]`
    - `local-transcriber remote-session status [--json]`
    - `local-transcriber remote-session stop [--force]`
  - Launcher: `scripts/start-remote-session.ps1` com parada supervisionada por Ctrl+C.
- **Comportamento de Execução:**
  - Por padrão, `remote-session start` opera em primeiro plano (*foreground*), mantendo a supervisão viva e capturando `Ctrl+C` para realizar o desligamento gracioso.
  - Suporte à execução em segundo plano (`--background`) para rotinas que desacoplam a inicialização da janela de terminal.
  - Armazenamento de estado efêmero em `%LOCALAPPDATA%\LocalTranscriber\remote\session.json`.
- **Validação de Propriedade:**
  - Antes de desligar um PID, inspeciona o processo via Windows CIM/WMI ou checagem de processo no sistema operacional, validando timestamp de criação e linha de comando.
- **Rollback Transacional:**
  - Persistir `prepared` antes do spawn, `gateway` após identificar o processo, `activating` antes do Serve e `active` após conferir a configuração. Temporários usam flush/fsync e replace. Falhas só limpam estado depois de rollback comprovado; efeitos incertos ou rollback que falha preservam evidência.
  - Recuperação via `stop` confirma ausência do mapping antes de terminar o processo e limpar o journal. Configuração alheia, desconhecida ou com múltiplos hosts/handlers bloqueia off. Journal incompleto sem PID comprovado ou corrompido exige reconciliação manual; nunca equivale a ausência de sessão.
  - A trava cobre start/stop desta aplicação, sem CAS entre clientes externos Tailscale. Não editar Serve por outros clientes durante a sessão. A durabilidade contra queda de energia não foi homologada.
  - Evidência e limites no [complemento posterior](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md); o relatório anterior não constitui aprovação do gate atual.

### Etapa 2 — Seleção Remota de Matérias, Rate Limiting e Blindagem (Próximo Worker)

- **Objetivo:** Permitir que o cliente móvel consulte matérias autorizadas para vincular o upload, aplicando controle rigoroso de frequência de requisições.
- **Requisitos de Design:**
  - **Allowlist de Matérias:**
    - Configuração em `gateway.json`: `"allowed_subjects": ["uuid1", "uuid2"]` ou flag `"allow_all_subjects": false`.
    - Endpoint restrito `GET /remote/v1/subjects` retornando apenas `id` e `name` das matérias presentes na allowlist.
    - O cliente não pode criar ou editar matérias remotamente (operações exclusivas da interface local do Core).
  - **Rate Limiting em Memória/Gateway:**
    - Algoritmo de Token Bucket ou janela deslizante indexado por `identity_hash`.
    - Limites diferenciados:
      - Obtenção de sessão e consulta de progresso: até 30 req/min.
      - Início de uploads e criação de jobs: até 5 req/min.
    - Excedentes retornam `429 Too Many Requests` com cabeçalho `Retry-After`.
  - **Manutenção de Barreiras Existentes:**
    - Preservar integridade dos testes de validação de `Host`, `Origin` HTTPS estrito e verificação CSRF HMAC-SHA256 vinculada à identidade e sessão.
    - Bloqueio persistente de rotas administrativas e modelos.

### Etapa 3 — Protocolo de Upload Particionado e Tolerância a Quedas (Worker Subsequente)

- **Objetivo:** Viabilizar uploads robustos de grandes arquivos de áudio (aulas de até 3 ou 4 horas) mesmo em redes móveis instáveis, com retomada automática e integridade garantida.
- **Especificação do Protocolo de Chunks:**
  1. `POST /remote/v1/uploads/resumable` (Cabeçalho `Idempotency-Key`, `X-Total-Bytes`, `X-Filename`, `X-Title`, `X-Subject-Id`, `X-Expected-Sha256`).
     - Aloca upload em `gateway.sqlite3` em estado `uploading`, gerando `upload_token` e diretório temporário isolado em `%LOCALAPPDATA%\LocalTranscriber\remote\incoming\<upload_id>\`.
  2. `PATCH /remote/v1/uploads/resumable/{upload_id}` (Cabeçalho `Upload-Offset`, `Content-Length`, corpo binário do chunk).
     - Valida `Upload-Offset` contra o tamanho atual já persistido no arquivo `.part`. Se houver divergência, retorna `409 Conflict` com cabeçalho `Current-Offset` para reconciliação do cliente.
     - Anexa bytes de forma estrita.
  3. `GET /remote/v1/uploads/resumable/{upload_id}`:
     - Permite ao cliente consultar o offset atual antes de retomar o envio após queda de conexão.
  4. Finalização:
     - Quando o total de bytes declarados for alcançado, o gateway calcula o SHA-256 final e confere com o esperado.
     - Se válido, importa o arquivo final no `MediaLibrary` do Core, cria o registro de gravação e associa ao `subject_id`.
  5. Expiração e Limpeza:
     - Uploads não atualizados por mais de 24 horas são expirados e limpos automaticamente pelo gateway.

---

## 4. Guia Operacional e Modos de Falha

### 4.1 Pré-requisitos do Operador
1. Tailscale instalado no notebook e conectado à conta do usuário (`tailscale status`).
2. O dispositivo móvel (iPad) deve estar conectado à mesma tailnet.
3. Configuração do gateway criada em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.json` definindo `enabled: true`, `allowed_identities`, `allowed_hosts`, `allowed_origins` e `subject_id`.
4. Core API em execução (`local-transcriber serve` ou via `scripts/start-local-transcriber.ps1`).

### 4.2 Matriz de Falhas e Comportamento Fail-Closed

| Cenário de Falha | Diagnóstico pelo Sistema | Ação e Resposta Operacional |
| :--- | :--- | :--- |
| **Tailscale ausente ou deslogado** | `tailscale.exe` não encontrado ou `BackendState != Running` | Aborta `start` com `TailscaleNotFoundError` ou `TailscaleNotRunningError`. Nenhuma porta aberta. |
| **Core API inativo na 8765** | Probe de conexão local falha | Aborta `start` alertando que o worker do core precisa estar rodando antes de aceitar sessões remotas. |
| **Porta 8766 ocupada** | Conflito de bind local | Verifica se é sessão prévia. Se desconhecido, fail-closed (`RemoteSessionConflictError`). |
| **Serve já mapeado para outro alvo** | `tailscale serve status` aponta para outro backend | Não sobrescreve. Aborta com erro de conflito de proxy. |
| **Processo gateway encerrou anormalmente** | PID não responde ou foi reciclado pelo SO | `stop` e `status` detectam divergência de `CreationDate` ou ausência de PID, limpam estado efêmero e desativam o serve sem tentar matar processo alheio. |
| **Tentativa de uso de Tailscale Funnel** | Cabeçalho `Tailscale-Funnel-Request` presente | Gateway bloqueia imediatamente com **403 Forbidden**. |

---

## 5. Portão de Qualidade e Critérios de Transição

- **Nível 1 — Mocks Sintéticos Locais (Obrigatório nas Etapas 1 a 3):**
  - Todas as chamadas de subprocesso do Tailscale (`tailscale status`, `tailscale serve`) devem possuir executores mockados determinísticos em `tests/test_remote_session.py`.
  - Nenhuma dependência externa ou conexão de rede física nos testes automatizados (`autouse` no-network socket).
  - Execução de testes sempre com `--basetemp` em diretório temporário único.
- **Nível 2 — Gate Físico Pré-Disponibilização (Etapa 8J-B Futura):**
  - Validação real de ponta a ponta com Tailscale ativo em máquina de homologação e iPad real enviando amostra de áudio via Atalho do iOS.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.
