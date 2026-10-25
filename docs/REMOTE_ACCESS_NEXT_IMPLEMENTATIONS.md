# Planejamento das Próximas Implementações de Acesso Remoto

**Data:** 2026-10-25  
**Baseline:** `0.7.1` (Commit `21fa5621d2bb2c49665b6d1fc4f7907ac0539d6a` + alterações locais da Etapa 1)  
**Status:** Etapa 0 Concluída e Aprovada Sinteticamente (Fechamento Pré-Gate 1); Etapa 2 pendente de autorização formal
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

### Etapa 2: Entrada Restrita e Governança de Acesso (Proposta Técnica)
- **Seleção Remota de Matérias (`GET /remote/v1/subjects`):** Endpoint mínimo que lista **exclusivamente as matérias configuradas na allowlist do operador**, e não todas as cadastradas no sistema. A consulta deve ser feita diretamente via `Repository` local do Core, sem criar acoplamento ou dependência de chamada HTTP ao Core API.
- **Validação de Entrada:** O upload passa a exigir a matéria vinculada, rejeitando requisições sem matéria autorizada com `400 Bad Request` e preservando compatibilidade com o campo `subject_id` legado.
- **Controle de Taxa (*Rate Limiting*):** Mecanismo de limitação de requisições em memória, indexado por `identity_hash` (hash criptográfico de `Tailscale-User-Login`) com limite finito de memória (*bounded*), sem armazenar logins brutos. Retorna status `429 Too Many Requests` e cabeçalho `Retry-After`. Limites numéricos são propostas a calibrar antes da autorização formal.
- **Preservação de Fronteiras e Erros Padronizados:**
  - Requisição sem cabeçalho `Tailscale-User-Login`: retorno `401 Unauthorized`.
  - Requisição contendo `Tailscale-Funnel-Request`: rejeição imediata com `403 Forbidden`.
  - Validação estrita de cabeçalhos `Host` e `Origin` e proteção CSRF.
  - Desativação total de rotas administrativas e documentação interativa (OpenAPI) no gateway.

### Etapa 3: Protocolo de Upload Resumable Real (Proposta Técnica)
- **Distinção Conceitual:** Upload resumable exige divisão em partes (*chunks*), verificação contínua de offset e retomada após interrupções de conexão móvel. Streaming simples ou retentativa de arquivo completo (*retry*) não constituem upload retomável.
- **Armazenamento e Separação de Dados:** Os bytes e chunks de mídia residem estritamente em **arquivos locais em disco** no diretório de staging do gateway. O banco `gateway.sqlite3` armazena exclusivamente **metadados, offsets, claims de posse e status de validação**. Nenhum BLOB de áudio é inserido no SQLite.
- **Estrutura Proposta de Metadados (`gateway.sqlite3`):**
  - Tabela `remote_resumable_sessions`: campos propostos `upload_id` (PK), `identity_hash`, `subject_id`, `filename`, `total_bytes`, `received_bytes`, `expected_sha256`, `state`, `created_at`, `updated_at`.
  - Tabela `remote_resumable_chunks`: campos propostos `upload_id`, `chunk_index`, `offset_start`, `offset_end`, `chunk_sha256`, `received_at`.
  - O banco do Core (schema v4) permanece estritamente inalterado e não lê tabelas do gateway.
- **Fluxo Proposto de Endpoints:**
  - Inicialização (`POST /remote/v1/upload/init`): Idempotente, gera identificador opaco (`upload_id`), valida tamanho total e associa a posse ao `identity_hash`.
  - Verificação de Progresso (`GET /remote/v1/upload/{upload_id}/offset`): Retorna o total exato de bytes persistidos em disco antes do envio de novos blocos.
  - Transmissão de Partes (`PATCH` ou `POST .../chunks`): Gravação em arquivo temporário com `fsync`, validação de checksum por bloco e SHA-256 consolidado ao final.
- **Governança de Armazenamento:** Implementação de TTL para expiração e purga de uploads incompletos, quotas de espaço em disco e timeouts finitos de inatividade.
- **Finalização e Integração com o Core:** Consolidação atômica e importação no Core executada diretamente via biblioteca e repositório local compartilhado (`Repository` do Core), e não via chamada HTTP ao Core API. O endpoint de upload legado existente (`POST /remote/v1/uploads`) permanece funcional como rota alternativa direta.
- **Janela de Ambiguidade de Commit:** Caso a mídia seja importada no Core mas a confirmação no gateway falhe, o gateway deve responder com `409 Conflict` (*fail-closed*), impedindo duplicações ou atribuições incorretas de mídia.
- **Formatos e Dispositivos:** O contêiner M4A é aceito conforme o backend, permanecendo a compatibilidade de codec do dispositivo gravador pendente de validação física. Não serão feitas promessas prematuras de uploads de 3 a 4 horas ou retomada transparente na UI antes de medições práticas em rede.

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
