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

## 8H: validacao independente apos publicacao

Commit d157c5c publicado em main. O workflow Windows installation concluiu com
status success em runner windows-latest independente, com Python 3.13 x64:
instalacao sem extra dev/modelos, pacote/assets, HTTP e SQLite sintetico aprovados.
Nao e prova de inferencia/qualidade, todo hardware ou outros sistemas operacionais.
[Validacao remota e limites](PHASE_08H_POSTPUBLICATION_WINDOWS_VALIDATION_2026-10-13.md).

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

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 foi posteriormente autorizada e entregue; veja o registro abaixo.

## Etapa 8J — Etapa 2: Matérias autorizadas e rate limiting (2026-10-25)

- **Status**: Implementada e validada sinteticamente, incluindo complemento de revisão.
- `GET /remote/v1/subjects` retorna apenas `id` e `name` das matérias autorizadas, diretamente do Repository.
- `allowed_subjects` exige allowlist; fallback para `subject_id` legado somente com chave ausente. Nulo explícito e lista vazia são rejeitados, inclusive com legado.
- `X-Subject-Id` seleciona a matéria antes de claims e bytes, vinculando-a ao fingerprint de idempotência. Replays legados retornam 409, sem apagar claims.
- Rate limiting por HMAC da identidade: burst de 30 tokens para leitura e 5 para mutações; reposição de 0.5/s e 1/12s; máximo de 100 identidades e TTL de 300s. Excesso retorna 429 com Retry-After antes de consumir chaves de idempotência.
- Worker registrou 420 testes aprovados, incluindo 120 de gateway, Ruff, formatação e pip check. Coordenador confirmou a correção, 11 testes de configuração, Ruff, formatação, pip check e git diff --check.
- Schema core v4, worker único e barreiras de segurança preservados. Homologação física Tailscale/iPad permanece pendente.
- **Próximo passo**: Etapa 3 (upload particionado/resumable), não iniciada e dependente de autorização explícita.
- [Plano](REMOTE_ACCESS_STAGE2_INTEGRATION_PLAN.md) e [evidências](PHASE_08J_STAGE2_REMOTE_SUBJECTS_AND_RATE_LIMIT_2026-10-25.md).
