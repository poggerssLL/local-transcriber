# Roadmap

1. Fundação e persistência — concluída.
2. Biblioteca de mídia e exportadores — concluída.
3. Engine Faster Whisper e CLIs — concluída.
4. Fila persistente — concluída.
5. API FastAPI e SSE — concluída.
6. Interface web — concluída.
7. Integração e validação real — concluída.
7B. Aceleração CUDA local e resiliência operacional da fila — concluída.
8. Resumo Estruturado com Ollama local e integração web completa — concluída.
8B. Manutenção de baseline, validação estática e consolidação factual — concluída.
8C. Estilo e separação dos testes de retries/expiração — concluída; publicação conjunta com Etapa 8/8B autorizada em 2026-10-05.
14. 8I. Opção opt-in de resumo estruturado via Sign in with ChatGPT — concluída.
9. Futuras fases de diarização, tempo real contínuo e Home Assistant — não iniciadas.

Após a Etapa 3, duas validações reais antecipadas confirmaram o fluxo CPU `int8` com
modelo local, exportações e persistência. Os RTFs observados foram 1,612 e 0,4778, mas
duas amostras curtas não permitem garantir desempenho em uma gravação de 1h40. A projeção
de aproximadamente 47,8 minutos derivada do segundo RTF não é uma medição real de carga
longa. A Etapa 7 adicionou uma terceira execução real curta e concluiu o caminho feliz
integrado, sem transformar essa evidência limitada em uma caracterização de carga longa.

Cada fase deve respeitar os invariantes de `PROJECT_CONTRACT.md` e incluir testes
proporcionais ao risco antes de avançar.

A Etapa 4 confirmou deterministicamente fila SQLite, worker local sequencial, progresso,
cancelamento, retry e recuperação por lease. A Etapa 7 confirmou uma execução real pela
fila, mas cancelamento, retry e recuperação continuam cobertos de modo determinístico por
engine falso até uma validação operacional específica.

A Etapa 5 expôs os serviços locais sob `/api`, com upload progressivo, fila obrigatória,
streaming controlado de mídia e exportações, SSE persistente com replay e worker integrado
ao ciclo de vida. A validação usou TestClient, mídia sintética, engine falso e runtime
temporário; não executou inferência real nem baixou modelos.

A Etapa 6 adicionou a interface web vanilla servida pela própria aplicação, sem build,
CDN ou serviço externo. Painel, matérias, biblioteca, configuração de transcrição, fila,
leitura sincronizada, exportações e modelos usam a API da mesma origem. Testes automatizados
e inspeção real no navegador usaram somente mídia, jobs e transcrições sintéticos; a Etapa
7 complementou essa evidência com uma amostra curta controlada, sem alterar a interface.

A correção complementar 5C removeu a contenção de escrita causada pelo polling do worker
com fila vazia. A pré-consulta é somente leitura, enquanto recuperação e reivindicação
continuam atômicas sob `BEGIN IMMEDIATE`; falhas SQLite transitórias recebem retry limitado.
A correção permanece preservada na Etapa 7.

A correção complementar 6B tornou o estado assíncrono do frontend monotônico. Cargas,
pesquisas, leituras, exportações e erros obsoletos não substituem mais o contexto recente;
o SSE usa cursor inicial do snapshot e sequência independente por job para rejeitar replay,
duplicação, regressão e callbacks de listeners encerrados. O schema continua v4, a operação
continua offline e foi preservada na Etapa 7.

A Etapa 7 concluiu a validação integrada do caminho feliz com mídia local controlada:
importação, FastAPI, fila, Faster Whisper em CPU `int8`, SSE persistente, FTS5, leitura,
Range e TXT, Markdown, SRT, WebVTT e JSON. O iniciador supervisionado do Windows mantém
host loopback e consumidor único. A 7B validou também CUDA `int8_float16` em uma amostra
curta após instalação explícita de CUDA 12/cuBLAS 12/cuDNN 9, sem download de modelo,
serviço externo ou alteração global de `PATH`. Ela bloqueou ainda a exclusão de gravação
enquanto há job ativo, evitando a interrupção do worker observada operacionalmente.

A Etapa 8 integrou a síntese pedagógica automatizada via Ollama local (`qwen2.5:3b`)
utilizando Map-Reduce temporal por blocos de 20 minutos, gerando artefatos sidecar
`transcript.resumo.md` e `transcript.resumo.json`. A interface web foi expandida com
painel interativo de leitura (tese central, resumo executivo, roteiro de podcast com cópia,
glossário com sincronização de timestamps no player de mídia, flashcards com revelação
ativa e downloads diretos de resumo). Foram adicionados 19 testes automatizados com mocks
(totalizando 134 testes aprovados no repositório). A política de privacidade, execução offline
e imutabilidade dos arquivos originais permanece integralmente respeitada.

A Etapa 8B realizou a manutenção e consolidação factual da baseline após a Etapa 8.
A suíte completa atingiu 141 testes Python aprovados (26 testes no módulo e rotas de resumo),
sintaxe JavaScript e compilação Python íntegras, dependências validadas pelo `pip check` e
hashes SHA-256 preservados nos oito arquivos pré-existentes da etapa. Foram registradas
as 10 advertências Ruff E501 e diferenças de formatação confinadas aos arquivos pré-existentes,
bem como a sensibilidade transitória intermitente observada no teste de retries de heartbeat
em `tests/test_queue.py` (falha na primeira execução e retries efetivos com causa desconhecida).
As contradições documentais sobre a presença do Ollama local no escopo foram saneadas sem
relaxamento de privacidade ou segurança. Etapa 9 não foi iniciada.

## Manutenção 8C

142 testes aprovados, Ruff global e formatação aprovados. Clock controlado no
teste de retries e regressão separada da margem expirada; nenhuma alteração
no heartbeat de produção ou no schema. A dívida de estilo da 8B foi resolvida;
a causa histórica da falha intermitente não foi inferida. Aviso pip de distribuição
inválida permanece, sem repair/install. Etapas futuras não iniciadas.
[Relatório 8C](PHASE_08C_STYLE_AND_HEARTBEAT_TESTS_2026-10-05.md).

## Diagnóstico 8D (2026-10-06)

Ambiente ativo 0.7.1/import de src confirmado; pip check exit 0 com aviso associado
a dois dist-info antigos prefixados por til (0.6.2/0.7.0), preservados. Ollama local
0.35.1 respondeu e qwen2.5:3b está presente. Sondagem CTranslate2 confirmou uma GPU
e int8_float16 sem erro, e CPU int8. Não houve inferência real, reparo/instalação,
limpeza de fixtures, mudança de versão/schema ou início da Etapa 9. Plano de reparo
reversível e validação sintética documentado; execução ainda pendente.
[Relatório 8D](PHASE_08D_ENVIRONMENT_PREFLIGHT_2026-10-06.md).

## Manutenção 8E (2026-10-06) — estado atual

Aviso de distribuição inválida resolvido por quarentena reversível de somente
os dois dist-info antigos. pip check exit 0 sem aviso; pacote ativo 0.7.1 e import
preservados. 26 testes pytest de resumo/API aprovados com mocks, sem inferência real.
Sem reinstalação, exclusão de fixtures, mudança de código, versão ou schema.
Próximo passo: validação sintética real CPU/CUDA/Ollama, com modelos existentes.
O diagnóstico 8D acima registra a situação anterior ao reparo.
[Relatório 8E](PHASE_08E_ENVIRONMENT_REPAIR_2026-10-06.md).

## Manutenção 8F: estado atual (2026-10-06)

Inferência small CPU int8 e CUDA int8_float16 concluída com tom sintético 2 s;
zero segmentos, sem prova de precisão de fala. Ollama qwen2.5:3b concluiu
map/reduce e persistiu Markdown/JSON com texto sintético separado. Fonte preservada,
5/5 termos; inspeção encontrou repetição e timeline vazia, portanto qualidade
não aprovada integralmente. 142 testes, Ruff/formatação e pip check aprovados.
Harness opt-in novo; núcleo/versão/schema preservados. Reviewer Gemini despachado
via Orca; done aguarda consentimento de IPC. Próximo: gate de qualidade/fala
sintética antes da Etapa 9. Diagnósticos 8D/8E acima são históricos. Sem commit/push.
[Validação 8F e limites](PHASE_08F_SYNTHETIC_NATIVE_VALIDATION_2026-10-06.md).

## Manutenção 8H: instalação para terceiros (2026-10-13)

Repositório público e main remoto confirmados em 5cfc7b8. Novo instalador
Windows x64/Python 3.13 cria venv e instala pacote normal sem extra dev, modelos
ou daemons automáticos. Guia ZIP/Git, CPU primeiro, download explícito, Ollama
opcional e diagnóstico disponíveis. LICENSE pessoal/não comercial escolhido
expressamente por Erick e incluído no pacote; não concede uso comercial.
Snapshot publicado mais entrega mínima instalado em venv novo no mesmo host:
wheel com seis assets e licença, CLI, HTTP/interface e SQLite sintético aprovados,
sem copiar modelos/dados e sem inferência. Suíte existente: 150 pass; Ruff,
formatação, sintaxe e pip check aprovados. Workflow Windows preparado; não
executado no GitHub durante a validação; publicação autorizada depois por Erick.
Não homologados outro computador/OS,
ARM, offline inicial ou qualidade semântica. 8G continua exigindo complemento.
[Guia de instalação](INSTALLATION.md) e
[relatório 8H e limites](PHASE_08H_GITHUB_INSTALLATION_2026-10-13.md).
Os estados datados anteriores são históricos, sem ampliação de Etapa 9.

## Manutenção 8G: estado registrado (2026-10-07)

Harness com gabarito de seis fatos/timestamps e fala SAPI sintética de 36,466 s.
Inferência real small CPU int8 (25,545 s) e CUDA int8_float16 (6,445 s): seis segmentos,
WER 0,0, seis âncoras e timestamps válidos. Ollama qwen2.5:3b processou texto sintético
separado; prompts corrigidos para estrutura/timestamps, extensão proporcional,
preservação dos atores e eliminação de duplicatas textualmente idênticas.
150 testes aprovados; regressões de resumo/qualidade após ajustes e Ruff/formatação
aprovados. Pacote 0.7.1/schema 4 e fixtures antigas preservados, sem commit/push.
Indicadores técnicos passaram, mas leitura manual ainda encontrou redundância e
ambiguidade de atores na tese: qualidade semântica integral exige complemento.
Não é E2E fala/fila/API/UI nem fala humana/carga longa. Etapa 9 não iniciada.
Próximo: resolver fidelidade/concisão com gabarito independente antes de ampliar
validação; preservar artefatos em output, com basetemp dos testes distinto.
[8G, evidência preservada e limitações](PHASE_08G_QUALITY_AND_SYNTHETIC_SPEECH_2026-10-07.md).
Os estados 8D/8E/8F datados acima são históricos; IPC pendente anterior não é estado atual.

## 8H: validacao independente apos publicacao

Commit d157c5c publicado em main. O workflow Windows installation concluiu com
status success em runner windows-latest independente, com Python 3.13 x64:
instalacao sem extra dev/modelos, pacote/assets, HTTP e SQLite sintetico aprovados.
Nao e prova de inferencia/qualidade, todo hardware ou outros sistemas operacionais.
[Validacao remota e limites](PHASE_08H_POSTPUBLICATION_WINDOWS_VALIDATION_2026-10-13.md).

## Etapa 8I — Opção opt-in de resumo estruturado via Sign in with ChatGPT (2026-10-24)

A Etapa 8I implementou a opção de síntese pedagógica estruturada utilizando autorização
oficial "Sign in with ChatGPT" e o plano de assinatura ChatGPT do usuário, mantendo o Ollama
local (`qwen2.5:3b`) como motor padrão e 100% offline. O transporte LLM foi desacoplado do
algoritmo Map-Reduce temporal em `TranscriptSummarizer` através da interface abstrata `LLMTransport`
e suas implementações `OllamaTransport` e `ChatGPTTransport`.

A autenticação segue rigorosamente o padrão OAuth 2.0 PKCE (S256) e OIDC para ferramentas open
source, com geração e conferência de `state` e `nonce` criptográficos, callback loopback
supervisionado, validação de assinatura RS256/JWKS em Python puro (sem bibliotecas externas pesadas),
conferência de `iss`, `aud`, `exp` e `nonce`, escopo `chatgpt.tokens.use.direct`, rotação automática
de refresh tokens e armazenamento seguro de credenciais em `%LOCALAPPDATA%\LocalTranscriber\auth`
fora do Git.

A inferência com ChatGPT consulta previamente `GET /v1/models` para validar se o modelo `gpt-6-luna`
está disponível no catálogo da conta conectada (falhando explicitamente com `ChatGPTModelUnavailableError`
caso ausente, sem substituição silenciosa). A requisição de geração é enviada exclusivamente para
`POST /v1/responses` com `store: false`, `stream: true`, `model: "gpt-6-luna"`, `reasoning: {"effort": "low"}`
e texto integral do chunk ou redução. O consumo do stream SSE aguarda o evento terminal `response.completed`
e trata `response.failed`, `response.incomplete` e erros HTTP (401/403/429/503) sem fallback silencioso para
o Ollama e sem persistir resumos parciais.

A interface web foi atualizada com seletor explícito de provedor (Ollama vs ChatGPT), barra de status
de conexão com botões de conectar/desconectar e aviso prévio de consentimento antes de qualquer transmissão
de texto de transcrição para a nuvem. A CLI recebeu `--provider {ollama, chatgpt}` e comandos `auth chatgpt status`
e `auth chatgpt logout`. O formato estruturado `TranscriptSummary` (schema 1.0.0) e sidecars `.resumo.md` e
`.resumo.json` foram estritamente preservados, enriquecendo os metadados de proveniência com o provedor utilizado.
A suíte de testes foi expandida para 186 testes automatizados com mocks determinísticos (36 novos testes cobrindo
autenticação, transporte, Map-Reduce e API), sem qualquer dependência ou chamada real à rede em testes.
[Relatório da Etapa 8I](PHASE_08I_SIGN_IN_WITH_CHATGPT_SUMMARIZER_2026-10-24.md).


## Etapa 8J-A — Gateway Privado FastAPI em Loopback para Ingestão Remota (2026-10-24)

- **Status**: Concluída (validada sinteticamente com 83 testes determinísticos).
- **Entregas**:
  - Módulo `src/local_transcriber/remote_gateway.py` com aplicação FastAPI desacoplada da core API, desligada por padrão (`remote/gateway.json`), vinculada exclusivamente ao loopback `127.0.0.1` (porta padrão `8766`, configurável via CLI) sob o prefixo `/remote/v1`.
  - Banco de estado `remote/gateway.sqlite3` gerenciando idempotência e escopo de propriedade sem alterações no schema v4 do core database.
  - Autenticação e autorização por cabeçalho `Tailscale-User-Login` contra allowlist (401 se ausente, 403 se não autorizado/duplicado; bloqueio de `Tailscale-Funnel-Request`), prevenindo IDOR em gravações e jobs.
  - Validação estrita de `Host` bare e `Origin` HTTPS exato, cookie de sessão com `session_id` aleatório e token CSRF assinado por HMAC-SHA256 derivado de segredo `remote/csrf.key` protegido com ACL Windows (`icacls`).
  - Defesa em profundidade contra DoS de upload: `Content-Length` obrigatório (411), contagem estrita de bytes de fato recebidos no streaming, timeout da recepção do corpo (`request_timeout_seconds`), checagem antecipada de disco livre com lock serializando uploads no gateway contra TOCTOU interno (concorrência com core não medida em hardware real), e sanitização de `DuplicateMediaError` ou colisões SHA.
  - Idempotência com falha fechada segura (409) em caso de ambiguidade pós-crash quando a mídia já existe no core, prevenindo IDOR. Resposta 410 com liberação transacional de claim para gravações deletadas.
  - Comando CLI `local-transcriber remote-gateway serve --host 127.0.0.1 --port 8766`.
  - Suíte de 83 testes determinísticos em `tests/test_remote_gateway.py` (e 63 regressões do core) cobrindo segurança, I/O, concorrência, idempotência com recuperação pós-falha e sanitização de logs.
- **Próxima etapa (8J Etapa 1)**: Ciclo de vida da sessão privada temporária, controle Tailscale Serve e verificação fail-closed de propriedade de processo.
[Relatório da Etapa 8J-A](PHASE_08J_REMOTE_GATEWAY_2026-10-24.md).


## Etapa 8J — Etapa 1: Sessão Privada Temporária e Orquestração Tailscale Serve (2026-10-25)

- **Status**: Complemento de recuperação implementado localmente; gate pendente de revisão independente do coordenador. 101 testes de sessão, 8 de CLI e 85 de gateway aprovados (194 focados). Evidência sintética, sem homologação física.
- **Entregas**:
  - Plano arquitetural e contrato revisável em `docs/REMOTE_ACCESS_INTEGRATION_PLAN.md` cobrindo fronteiras, invariantes e sequenciamento das etapas 1 a 3.
  - Módulo `src/local_transcriber/remote_session.py` com `TailscaleCli`, `ProcessVerifier` e `RemoteSessionManager`.
  - Hardening pré-gate da Etapa 0: ProcessVerifier fail-closed com Win32 ctypes 64 bits e correspondência exata de argumentos de linha de comando; serve_status estrito e recusa incondicional de Funnel e conflitos prévios; status observacional; stop transacional com preservação de arquivo de estado em falhas; serialização via trava `.session.lock`; validação numérica de portas (1-65535); probe de prontidão autenticado no gateway (`GET /remote/v1/health`); entrypoint modular `python -m local_transcriber.cli`.
  - Comandos CLI operacionais: `local-transcriber remote-session start` (foreground supervisionado com parada limpa via Ctrl+C ou `--background`), `status` (tabular ou `--json`) e `stop` (idempotente e seletivo).
  - Launcher PowerShell opcional `scripts/start-remote-session.ps1` com verificação de ambiente virtual e porta.
  - Orquestração de proxy reverso via Tailscale Serve estritamente na tailnet (Tailscale Funnel proibido e bloqueado), com desligamento seletivo pontual (`tailscale serve --https=443 off`) condicionado à comprovação do mapping próprio.
  - Preservação total do Core API (porta `8765`, consumidor único da fila SQLite) e dos jobs recebidos durante a abertura e encerramento de sessões remotas.
  - Journal antes de spawn/ativação; rollback seletivo; retenção de recuperação em falha de consulta/off/persistência/rollback; inspeção completa da porta Serve e regressões de concorrência/HANDLE 64-bit.
  - [Complemento posterior](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md) preserva os relatórios anteriores e corrige a interpretação de fechamento do gate.
- **Próximas etapas (dependem de revisão do complemento e nova autorização explícita)**:
  - **Etapa 2**: Seleção remota de matérias com allowlist (`GET /remote/v1/subjects`), rate limiting bounded por `identity_hash` e preservação de barreiras de segurança.
  - **Etapa 3**: Protocolo de upload particionado (*resumable chunks*) com banco isolado no gateway (`gateway.sqlite3`), mantendo o schema v4 do core imutável.
  - **Gate Físico (8J-B)**: Validação em hardware real com Tailscale ativo e dispositivo móvel (iPad).
[Relatório da Etapa 8J-1](PHASE_08J_STAGE1_REMOTE_SESSION_2026-10-25.md) e [Relatório de Hardening da Etapa 0](PHASE_08J_STAGE1_HARDENING_2026-10-25.md).


## Ferramentas do agente (2026-10-25)

Conclu?da a configura??o local dos MCPs GitHub e filesystem, instala??o da skill Impeccable e atualiza??o das regras de economia. Inicializa??o MCP real confirmada; nenhuma nova fase funcional do transcritor foi iniciada. Pr?ximas implementa??es continuam dependendo de autoriza??o pr?pria.


## Integra??o MCP Graphify (2026-10-25)

Conclu?da a integra??o MCP local do Graphify, com chamadas reais graph_stats e query_graph. Prefer?ncia por MCP para opera??es GitHub registrada em AGENTS.md. Atualiza??o do grafo n?o foi realizada nesta etapa; nenhuma fase funcional do aplicativo foi iniciada.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.


## Ferramentas Serena MCP (2026-10-25)

Integração de desenvolvimento Graphify → Serena e regras obrigatórias de leitura
cirúrgica, GitHub separado e commit/push direto. Evidências e pendências no
[relatório](PHASE_TOOLING_SERENA_MCP_2026-10-25.md). Esta manutenção não autoriza
nem inicia a próxima etapa funcional do aplicativo.

Serena validado por initialize, 21 ferramentas e leitura do método exato (72 de
1.212 linhas). Pesquisa oficial via MCP GitHub pendente por timeout; reabrir a
sessão para descoberta do novo MCP. Nenhuma alteração funcional do aplicativo.
