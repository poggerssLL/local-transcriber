# Estado atual do projeto

> Fotografia atualizada em 2026-10-25 após complemento de recuperação da Etapa 1/Etapa 0 da Fase 8J;
> gate pendente de revisão independente do coordenador; Etapa 2 não autorizada.
> estados datados anteriores e resultados 8C são históricos. Atualize ao fim de cada fase;
> não reescreva os relatórios históricos de fases concluídas.

O **Local Transcriber** é uma aplicação local para catalogar gravações e persistir o
ciclo de vida de transcrições. A arquitetura atual é um pacote Python com modelos de
domínio, biblioteca de mídia, engine desacoplado, fila persistente, worker local, CLI,
API FastAPI restrita ao localhost, interface web local, eventos SSE, exportadores determinísticos,
resumo estruturado com Ollama local e persistência de metadados em SQLite; mídias, modelos e
demais dados de runtime ficam fora do repositório.

- Versão do pacote: `0.7.1`.
- Schema SQLite: v4.
- Etapas concluídas: 1, fundação e persistência; 2, biblioteca de mídia e exportadores;
  3, Faster Whisper, gerenciamento explícito de modelos e CLI; 4, fila persistente;
  5, API HTTP local e SSE; 6, interface web local; 7, integração e validação real do MVP;
  7B, aceleração CUDA local e resiliência da exclusão durante jobs ativos; 8, resumo estruturado
  com Ollama local e integração web completa (visualização e download); 8B, manutenção de
  baseline, validação estática e consolidação factual da documentação; 8J-A, gateway privado
  FastAPI em loopback para ingestão remota.
- 8J Etapa 1/Etapa 0: implementação local complementada, pendente de revisão do coordenador.
  Journal persistido antes dos efeitos, retenção em falhas de rede/persistência/rollback e
  validação integral da porta Serve; 101 testes de sessão e 194 testes focados aprovados.
  Evidência sintética, sem Tailscale real. Estado `prepared` incompleto ou corrompido exige
  reconciliação manual e permanece bloqueado. Próxima ação: revisar o
  [complemento](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md), sem iniciar Etapa 2.
- Funcionalidades disponíveis: configuração de runtime, catálogo de matérias e gravações,
  importação e inspeção de mídia por PyAV, duplicidade exata por SHA-256, pesquisa FTS5,
  persistência do domínio, transcrição síncrona, enfileiramento, worker local sequencial,
  progresso e eventos persistentes, cancelamento, retry, recuperação por lease e exportação
  TXT, Markdown, SRT, WebVTT e JSON; API versionada sob `/api`, upload progressivo,
  streaming de mídia com Range, downloads de exportações e replay de eventos SSE por
  `Last-Event-ID`; módulo de sumarização pedagógica via Ollama local (`qwen2.5:3b`) com Map-Reduce
  temporal, geração de sidecars `.resumo.md` e `.resumo.json`, rotas de consulta, geração e download;
  interface web sem build e sem dependência de CDN para painel, matérias, biblioteca, fila,
  leitura sincronizada, exportação, modelos e painel interativo de resumo com tese central,
  roteiro falado para podcast, glossário com sincronização no player de áudio/vídeo, flashcards de
  fixação ativa e downloads diretos de resumo; a especificação OpenAPI JSON continua local e não
  existe visualizador HTML dos contratos; um único entrypoint expõe esses serviços. Gerações
  monotônicas, cancelamento de requisições e validação explícita do contexto impedem que resultados
  assíncronos obsoletos substituam a seleção atual. O iniciador `scripts/start-local-transcriber.ps1`
  verifica `.venv` e a porta escolhida, mantém o processo em primeiro plano e fixa loopback e um worker.
- Dependências validadas: PyAV 16.1.0, Faster Whisper 1.2.1, CTranslate2 4.8.2,
  FastAPI 0.116.2, Starlette 0.48.0, Uvicorn 0.52.4 e python-multipart 0.0.32.
- Manutenção 8C (2026-10-05) em checkout isolado com importação do pacote confirmada:
  142 testes Python aprovados (24 da fila); Ruff check global aprovado e 28 arquivos
  já formatados. Compilação de sintaxe de src/tests e git diff --check aprovados.
  pip check não encontrou dependências quebradas, mas emitiu aviso de distribuição
  inválida ~ocal-transcriber no ambiente existente, sem reparo de ambiente.
  Estilo dos quatro arquivos preserva AST funcional; três docstrings de testes
  foram refluídas. O teste de retries usa FakeClock estável para não competir
  com expiração real; regressão separada prova recusa após esgotar a margem
  de lease. A causa da falha histórica 8B não foi inferida retrospectivamente.
  Validação somente com mocks/fixtures sintéticos, sem inferência/modelos reais,
  download, daemon Ollama ou dados pessoais; versão 0.7.1 e schema v4 preservados.
- Próxima etapa: Etapa 2 da Fase 8J (seleção remota de matérias com allowlist e rate limiting) e Etapa 3 (upload particionado/resumable) conforme plano contratado em docs/REMOTE_ACCESS_INTEGRATION_PLAN.md.
- `local-transcriber serve` aceita somente `127.0.0.1` e um consumidor de fila por
  runtime. `Host` e `Origin` são validados, respostas não expõem caminhos físicos e a API
  não inicia downloads de modelos.
- O SSE usa consulta SQLite incremental e parametrizada por job e sequência, limita cada
  lote, drena backlog antes de aguardar e não relê todo o histórico a cada polling.
- Cada snapshot HTTP de job informa o último evento persistido. O navegador acompanha a
  última sequência aceita de cada job, inicia o SSE nesse cursor e descarta IDs repetidos,
  menores, fora de ordem ou pertencentes a listeners encerrados. O schema permanece v4.
- O worker consulta primeiro, sem lock de escrita, se existe job pendente ou lease vencida.
  Somente então entra em `BEGIN IMMEDIATE` e repete recuperação e seleção antes do
  compare-and-set. Falhas `SQLITE_BUSY` e `SQLITE_LOCKED` na reivindicação recebem retry
  curto e limitado; erros permanentes ou limite excedido encerram o controlador com falha
  registrada, em vez de ficarem ocultos em loop.
- A fila usa estados públicos preservados e fases operacionais separadas. A reivindicação
  é transacional e condicionada ao estado; a posse usa worker e lease renovável.
- Falhas SQLite transitórias do heartbeat têm retry limitado enquanto há margem segura.
  Perda definitiva ativa um sinal cooperativo e usa `LeaseOwnershipLost`, sem classificar
  a tentativa obsoleta como falha do engine nem alterar o job recuperado por outro worker.
- Execução após crash é `at least once`: jobs recuperados podem reiniciar a inferência.
  Somente a lease válida permite persistir progresso ou publicar. Pode haver breve
  sobreposição de computação até o worker obsoleto atingir um ponto cooperativo, mas a
  publicação final é transacional e limitada a uma transcrição por job.
- O cancelamento é cooperativo, o worker padrão processa um job por vez e não há timeout
  total artificial para gravações longas.
- Três validações reais confirmaram o modelo `small` multilíngue, carregamento local,
  inferência CPU `int8`, idioma detectado, VAD, timestamps por palavra, métricas, cinco
  exportações e recuperação de estado. A terceira percorreu FastAPI, fila, worker, SSE,
  interface web, busca e streaming de mídia em uma amostra curta controlada.
- A primeira execução registrou RTF 1,612. A segunda usou áudio de aproximadamente
  50,97 segundos, produziu 5 segmentos e 78 palavras e registrou cerca de 24,35 segundos
  persistidos, 25,26 segundos de parede, RTF 0,4778 e pico aproximado de 709,9 MiB.
- A segunda execução ficou aproximadamente 2,09 vezes mais rápida que tempo real. Caches,
  aquecimento, conteúdo e duração podem influenciar a diferença entre as duas medições.
- A terceira execução teve 18,23 segundos de mídia, 14,88 segundos de processamento
  persistido e RTF aproximado de 0,816, com 3 segmentos e 41 palavras. Uma amostragem de
  memória iniciada após a finalização observou cerca de 132,8 MiB de working set e 2.394,9
  MiB de memória privada no processo; não é medição de pico nem benchmark comparável.
- Uma observação operacional posterior reiniciou o computador com job em andamento; após a
  nova inicialização do serviço, a fila recuperou o estado persistido e o job concluiu.
  Isso confirma recuperação ponta a ponta, sem medir latência de lease ou qualidade do
  modelo.
- A estrutura temporal e os números principais foram validados, com erros observados em
  vocabulário técnico. Sem gabarito textual independente, nenhuma taxa de precisão foi
  calculada.
- No Windows, a aplicação registra apenas no processo atual os diretórios padrão de CUDA
  12 e cuDNN 9 antes de importar CTranslate2. Com CUDA Toolkit 12.8.2, cuBLAS 12 e cuDNN
  9.26.0.51 instalados explicitamente pelo operador, `config check` confirmou GPU e
  `int8_float16` sem erro. Não há modificação global de `PATH`.
- A comparação real com `small`, VAD e timestamps, em 33,97 s de mídia, registrou
  aproximadamente 118,32 s de processamento CPU `int8` (RTF 3,482) e 19,79 s em CUDA
  `int8_float16` (RTF 0,583). É uma amostra curta e inclui carregamento; não é benchmark
  de carga longa. A amostra controlada não teve segmentos ou palavras. O operador relatou
  testes posteriores de áudio em CUDA, sem métricas coletadas por esta entrega.
- A exclusão de uma gravação com job `pending` ou `running` agora recebe conflito e preserva
  gravação, mídia e job. Uma ausência excepcional de job reivindicado é tratada como perda
  de lease, sem encerrar o worker.
- Fora do MVP atual: diarização, microfone ao vivo e Home Assistant (a sumarização estruturada com Ollama local restringe-se estritamente ao localhost).

Referências: [contrato](PROJECT_CONTRACT.md), [arquitetura viva](FOUNDATION.md),
[roadmap](ROADMAP.md), [Etapa 1](PHASE_01_FOUNDATION.md),
[Etapa 2](PHASE_02_MEDIA_LIBRARY.md), [Etapa 3](PHASE_03_WHISPER_AND_CLI.md),
[validação real 3B](PHASE_03B_REAL_VALIDATION.md),
[segunda validação real 3C](PHASE_03C_SECOND_REAL_VALIDATION.md) e
[Etapa 4](PHASE_04_PERSISTENT_QUEUE.md),
[correção complementar 4B](PHASE_04B_LEASE_RELIABILITY.md) e
[Etapa 5](PHASE_05_LOCAL_API_AND_SSE.md) e
[correção complementar 5B](PHASE_05B_OFFLINE_DOCS_AND_INCREMENTAL_SSE.md) e
[Etapa 6](PHASE_06_WEB_INTERFACE.md) e
[correção complementar 5C](PHASE_05C_SQLITE_CONTENTION_RELIABILITY.md) e
[correção complementar 6B](PHASE_06B_ASYNC_CONCURRENCY_RELIABILITY.md) e
[Etapa 7](PHASE_07_MVP_INTEGRATION_AND_REAL_VALIDATION.md),
[correção complementar 7B](PHASE_07B_LOCAL_CUDA_ACCELERATION.md),
[Etapa 8](PHASE_08_STRUCTURED_SUMMARIZER_AND_WEB_INTEGRATION.md) e
[manutenção e validação de baseline 8B](PHASE_08B_MAINTENANCE_VALIDATION_2026-10-05.md).

Complemento atual: [manutenção 8C](PHASE_08C_STYLE_AND_HEARTBEAT_TESTS_2026-10-05.md).
Publicação conjunta da Etapa 8 e manutenções 8B/8C autorizada por Erick em
2026-10-05 e consolidada neste commit; SHA e push são verificáveis no Git.
Etapas futuras não iniciadas.

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

## Etapa 8I: resumo estruturado via Sign in with ChatGPT (2026-10-24) — estado atual

Implementada a opção de sumarização pedagógica estruturada utilizando autorização oficial
OAuth 2.0 PKCE / OIDC "Sign in with ChatGPT" e o plano de assinatura ChatGPT do usuário,
preservando o Ollama local (`qwen2.5:3b`) como motor padrão e 100% offline. O algoritmo Map-Reduce
temporal em `TranscriptSummarizer` foi desacoplado através da interface abstrata `LLMTransport`
(`OllamaTransport` e `ChatGPTTransport`).

A autenticação implementa PKCE S256, geração e conferência de `state` e `nonce` criptográficos,
callback loopback restrito a HTTP em `127.0.0.1` com TTL de 10 min, validação de `state` inclusive em erros,
escape HTML contra XSS, validação estrita de ID token (assinatura RS256 com chave pública JWKS
da OpenAI em Python puro sem dependências externas, `iss="https://auth.openai.com"`, `aud=client_id`,
`exp > now`, `nonce`), escopos oficiais (`openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`),
recurso `https://api.openai.com/v1`, preservação de `client_id` para reautorização (`id_token_hint`), rotação automática e
armazenamento em `%LOCALAPPDATA%\LocalTranscriber\auth` protegido por ACL NTFS nativa no Windows (`icacls`, falhando fechado) fora do Git.

A inferência valida `gpt-6-luna` no catálogo via `GET /v1/models` (contrato SIWC com array `models` contendo `slug` e `visibility`,
rejeitando sem substituição caso ausente e reportando `has_luna=False` em falhas) e consome SSE via `POST /v1/responses` (`store: false`, `stream: true`, `model: "gpt-6-luna"`,
`reasoning: {"effort": "low"}`) com `response.output_text.delta` e deduplicação até `response.completed`. Erros HTTP ou de inferência falham
explicitamente sem fallback para Ollama e sem persistir resumos parciais. A interface web inclui
seletor de provedor, barra de conexão e consentimento prévio antes do envio de texto para a nuvem.
O formato `TranscriptSummary` (schema 1.0.0) e sidecars `.resumo.md` e `.resumo.json` permanecem
inalterados, registrando proveniência (`provider="chatgpt"`). 186 testes unitários/integração
aprovados (36 novos testes determinísticos), Ruff check/format aprovados, pip check aprovado.
Nenhuma chamada de rede real a OpenAI e nenhum dado pessoal enviado ou persistido em repositório.
[Relatório da Etapa 8I](PHASE_08I_SIGN_IN_WITH_CHATGPT_SUMMARIZER_2026-10-24.md).


## Etapa 8J-A: Gateway Privado FastAPI em Loopback para Ingestão Remota (2026-10-24) — estado atual

Implementado o gateway FastAPI dedicado (`remote_gateway.py`), desativado por padrão (configuração em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.json`) e com binding restrito exclusivamente ao loopback `127.0.0.1` (porta padrão `8766`, configurável via CLI), para viabilizar o envio de áudio e acompanhamento de jobs a partir de dispositivos móveis autorizados (ex.: iPad via Tailscale) sob o prefixo `/remote/v1`, sem expor a API de gerenciamento local nem o sintetizador LLM (Ollama/ChatGPT).

O gateway possui banco de estado SQLite dedicado (`%LOCALAPPDATA%\LocalTranscriber\remote\gateway.sqlite3`) sem modificar o schema v4 do core database. Implementa:
1. Autenticação mandatória pelo cabeçalho `Tailscale-User-Login` fornecido por proxy reverso local confiável contra allowlist estática (`allowed_identities`); cabeçalho ausente ou vazio resulta em 401; duplicado ou não autorizado resulta em 403; requisições contendo `Tailscale-Funnel-Request` são rejeitadas com 403.
2. Binding público rejeitado (403) no nível do middleware HTTP.
3. Exigência estrita de `Host` (bare hostname em allowlist, rejeitando porta/path/query/fragment/userinfo com 400) e `Origin` HTTPS exato em mutações (sem barra final ou porta inesperada com 403), sem CORS, com cookie contendo `session_id` aleatório (`SameSite=Strict`, `HttpOnly`, `Secure` no caminho `/remote/v1`) e token CSRF HMAC-SHA256 vinculado à sessão e à identidade, derivado de segredo `remote/csrf.key` protegido com ACL NTFS nativa no Windows (`icacls`), validada e reaplicada no startup.
4. Prevenção de IDOR: registros e jobs são escopados pela chave HMAC da identidade no banco do gateway, proibindo a associação de `recording_id` completado a identidades distintas.
5. Proteção de streaming e concorrência: cabeçalho `Content-Length` obrigatório (411 se ausente ou chunked), contagem de bytes em streaming abortando com 413 ao exceder limites, timeout total da recepção do corpo (`request_timeout_seconds`, padrão 600s), checagem antecipada de espaço livre em disco (`min_free_disk_bytes`) com lock de upload assíncrono serializando o fluxo dentro do gateway para mitigar concorrência TOCTOU (concorrência com importações locais simultâneas no core não medida em hardware real), e sanitização de `DuplicateMediaError` ou colisões SHA-256 retornando 409 genérico.
6. Idempotência transacional e falha fechada: suporte a `Idempotency-Key`; `claim_upload` em estado `importing` recente retorna 409 busy; em retries pós-crash/timeout de claim `importing`, caso a mídia já exista no core repository, a requisição falha fechada com 409 sanitizado prevenindo IDOR (já que o schema v4 do core não armazena a identidade do gateway para provar a posse sem migração de banco); exclusão de gravação no core resulta em 410 no agendamento de jobs, liberando a claim no bloco `finally`.
7. CLI com comando `local-transcriber remote-gateway serve --host 127.0.0.1 --port 8766`.
8. Suíte de 83 testes determinísticos dedicados em `tests/test_remote_gateway.py` (100% aprovados) e 63 testes principais de regressão do core aprovados, com fixture de socket compatível com Windows.
9. Portão de segurança futuro: a segurança física em rede real depende do provisionamento de proxy privado (Tailscale), que não foi ativado nem exposto publicamente nesta etapa.
[Relatório da Etapa 8J-A](PHASE_08J_REMOTE_GATEWAY_2026-10-24.md).


## Ferramentas do agente (2026-10-25)

Ferramentas de desenvolvimento configuradas em `.codex/config.toml`: filesystem limitado ? raiz do projeto e GitHub autenticado via GitHub CLI, sem token em arquivo. Ambos responderam ? inicializa??o MCP real. Impeccable instalada em `.agents/skills/impeccable`; regras de economia incorporadas ao `AGENTS.md`. A branch foi atualizada por fast-forward; mudan?as locais anteriores foram preservadas. Ver [registro](PHASE_TOOLING_MCP_AND_SKILLS_2026-10-25.md).


## Integra??o MCP Graphify (2026-10-25)

MCP Graphify local configurado e validado por stdio: inicializa??o, listagem de dez ferramentas, graph_stats e query_graph reais. O grafo salvo possui 1.586 n?s e 4.542 rela??es; informa baseline anterior ao HEAD e pode estar desatualizado. A sess?o do agente precisa ser reaberta para descobrir o novo servidor.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.


## Serena MCP — ferramentas de desenvolvimento (2026-10-25)

Regras de leitura Graphify → Serena e uso exclusivo do MCP `github` separado
registradas em `AGENTS.md`. Pedidos diretos de commit/push não acionam revisão de
release nem leitura de memória externa. Instalação Serena isolada do aplicativo;
resultado da validação registrado no [relatório](PHASE_TOOLING_SERENA_MCP_2026-10-25.md).
Nenhuma etapa funcional do transcritor foi iniciada nesta manutenção.

Serena validado por initialize, 21 ferramentas e leitura do método exato (72 de
1.212 linhas). Pesquisa oficial via MCP GitHub pendente por timeout; reabrir a
sessão para descoberta do novo MCP. Nenhuma alteração funcional do aplicativo.
