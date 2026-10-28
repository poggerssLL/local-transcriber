# Arquitetura técnica do Local Transcriber

> Documento vivo e cumulativo da arquitetura atual. Os relatórios `PHASE_XX_*.md`
> preservam o estado histórico de cada etapa; esta visão deve acompanhar o sistema.

## Finalidade e estado

O **Local Transcriber** é uma aplicação local para catalogar gravações, executar
transcrição com Faster Whisper e exportar resultados estruturados sem depender de APIs
de IA em nuvem. A versão atual é `0.7.1`, usa schema SQLite v4 e concluiu:

1. fundação e persistência;
2. biblioteca de mídia, pesquisa e exportadores;
3. Faster Whisper, modelos explícitos e CLI;
4. fila persistente e worker local;
5. API FastAPI local e eventos SSE persistentes;
6. interface web local em HTML, CSS e JavaScript;
7. integração e validação real do MVP;
7B. aceleração CUDA local e resiliência da fila durante exclusão;
8. resumo estruturado com Ollama local e integração web completa;
8B. manutenção de baseline e validação estática factual;
8C. estilo e separação dos testes de retries/expiração;
8I. opção opt-in de resumo estruturado via Sign in with ChatGPT.

As futuras etapas de diarização, transcrição contínua em tempo real e integração com Home Assistant não foram iniciadas.

## Estrutura do repositório

```text
Local Transcriber/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── scripts/
│   └── start-local-transcriber.ps1
├── docs/
│   ├── FOUNDATION.md
│   ├── PROJECT_CONTRACT.md
│   ├── PROJECT_STATE.md
│   ├── ROADMAP.md
│   ├── DECISIONS.md
│   ├── KNOWN_ISSUES.md
│   └── PHASE_XX_*.md
├── src/local_transcriber/
│   ├── config.py
│   ├── database.py
│   ├── exceptions.py
│   ├── models.py
│   ├── repository.py
│   ├── media.py
│   ├── exporters.py
│   ├── models_manager.py
│   ├── transcription.py
│   ├── queueing.py
│   ├── api.py
│   ├── chatgpt_auth.py
│   ├── chatgpt_client.py
│   ├── summarizer.py
│   ├── web/
│   │   ├── index.html
│   │   ├── styles.css
│   │   ├── api.js
│   │   ├── async_state.js
│   │   ├── dom.js
│   │   └── app.js
│   ├── cli.py
│   └── __main__.py
└── tests/
```

O pacote usa layout `src/`, Python 3.11 ou superior e um único entrypoint instalável,
`local-transcriber`.

## Componentes e responsabilidades

- `config.py`: resolve configuração, diretórios de runtime e caminhos relativos seguros.
- `models.py`: define modelos de domínio imutáveis e suas validações.
- `database.py`: abre conexões SQLite e aplica migrações incrementais.
- `exceptions.py`: define falhas de domínio compartilhadas, incluindo perda de lease.
- `repository.py`: executa consultas parametrizadas e reconstrói o domínio.
- `media.py`: importa, inspeciona, cataloga e exclui mídia gerenciada.
- `exporters.py`: renderiza formatos determinísticos e registra artefatos.
- `models_manager.py`: lista, verifica e baixa modelos somente mediante confirmação.
- `transcription.py`: abstrai o engine, resolve perfis e coordena a transcrição.
- `queueing.py`: enfileira trabalhos e executa o worker local sequencial com leases.
- `api.py`: define os contratos `/api`, segurança HTTP, streaming, SSE e lifespan.
- `chatgpt_auth.py`: gerencia autenticação OAuth 2.0 PKCE / OIDC 'Sign in with ChatGPT', validação obrigatória de ID tokens RS256/JWKS, checagem de escopos (`openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`), inclusão de recurso `https://api.openai.com/v1`, preservação do `client_id` emitido na inscrição inicial para reautorização, rotação de refresh tokens e armazenamento seguro com ACL NTFS restrita (`icacls`) em `RuntimePaths.auth`.
- `chatgpt_client.py`: implementa transporte HTTP/SSE (`ChatGPTTransport`) com validação de catálogo oficial (`/v1/models`, array `models` com `slug` e `visibility`) exigindo `gpt-6-luna`, inferência exclusiva via `/v1/responses` (`reasoning: {'effort': 'low'}`, `store: false`, `stream: true`), streaming via `response.output_text.delta` com prevenção estrita de duplicação textual em `output_item.done` e `response.completed`.
- `summarizer.py`: orquestra a sumarização pedagógica Map-Reduce temporal desacoplada via `LLMTransport` (`OllamaTransport` ou `ChatGPTTransport`), persistindo artefatos `.resumo.md` e `.resumo.json` sob schema 1.0.0 com registro explícito de proveniência.
- `web/`: implementa a interface sem build, com assets locais e consumo seguro da API.
- `cli.py`: expõe os serviços existentes sem duplicar regras de negócio.
- `scripts/start-local-transcriber.ps1`: inicia o entrypoint instalado em primeiro plano,
  após verificar `.venv` e a disponibilidade da porta local solicitada.

## Configuração e RuntimePaths

`AppConfig.from_env()` usa `%LOCALAPPDATA%\LocalTranscriber` por padrão. Em testes ou
desenvolvimento, `LOCAL_TRANSCRIBER_DATA_DIR` pode indicar outro diretório absoluto.
`RuntimePaths` fornece:

```text
LocalTranscriber/
├── local_transcriber.sqlite3
├── media/
├── exports/
└── models/
```

Os diretórios são criados explicitamente, não durante a importação do pacote. Caminhos
persistidos usam `/`, são relativos ao runtime e rejeitam valores absolutos, prefixos de
unidade, barras invertidas e componentes `..`. A resolução final confirma confinamento.

Áudios, vídeos, modelos, bancos, transcrições pessoais, exportações, caches e temporários
permanecem fora do repositório e são bloqueados pelo `.gitignore`.

## Domínio e persistência

Os principais modelos são:

- `Subject`: matéria associada a gravações;
- `Recording`: metadados, hash, duração e caminho relativo da mídia;
- `TranscriptionJob`: ciclo `pending`, `running`, `succeeded`, `failed` ou `cancelled`;
- `JobPhase`: fase operacional separada entre `queued` e `completed`;
- `JobEvent`: progresso persistente e ordenado por job;
- `Transcript`: texto, idioma, probabilidade, configurações, métricas e segmentos;
- `Segment` e `Word`: intervalos temporais ordenados, com probabilidade opcional;
- `ExportedArtifact`: formato, MIME type, tamanho, hash e caminho relativo;
- `TranscriptionSettings` e `TranscriptionMetrics`: parâmetros efetivos e desempenho.

Identificadores são UUIDs, datas de criação usam UTC e os modelos validam intervalos,
probabilidades, hashes, nomes e estados antes da persistência.

SQLite armazena somente metadados. O schema v1 criou o domínio persistente; o v2 adicionou
configurações, métricas, metadados de exportação e FTS5; o v3 acrescentou a probabilidade
do idioma detectado. O v4 acrescentou fila, fases, progresso, tentativas, cancelamento,
posse por lease e eventos ordenados. Migrações publicadas são imutáveis, incrementais e
testadas em banco vazio e proveniente de cada versão anterior. Chaves estrangeiras são
habilitadas em cada conexão e todo conteúdo variável chega ao SQL por parâmetros.

## Biblioteca e inspeção de mídia

`MediaLibrary` aceita arquivo controlado ou stream binário. A importação:

1. sanitiza o nome e valida extensão e limites;
2. copia em blocos para `media/.incoming`, calculando SHA-256;
3. rejeita duplicidade exata dos bytes;
4. usa PyAV/FFmpeg para confirmar contêiner, stream de áudio e decodificação;
5. move atomicamente o temporário para `media/<ano>/<uuid>/<nome>`;
6. persiste os metadados e compensa o arquivo se o banco falhar.

A exclusão é recusada enquanto a gravação possui job `pending` ou `running`; gravação,
mídia e job são preservados até que o ciclo de trabalho chegue a estado terminal.

WAV, MP3, FLAC, M4A, OGG, MP4, MKV e WebM são extensões aceitas, mas a aceitação real
depende do contêiner e dos codecs disponíveis no PyAV instalado. Não há conversão,
normalização ou equivalência perceptual.

## Pesquisa e exportação

A pesquisa local usa SQLite FTS5 com tokenização Unicode e remoção de diacríticos.
Triggers mantêm título, matéria e conteúdo transcrito sincronizados. As consultas são
parametrizadas. Ranking e filtros avançados ainda são limitações conhecidas.

Renderizadores puros produzem bytes UTF-8 determinísticos com quebras `LF` em TXT,
Markdown, SRT, WebVTT e JSON. SRT e WebVTT aplicam convenções próprias de milissegundos;
Markdown e WebVTT escapam conteúdo. `TranscriptExporter` grava sob `exports/` e registra
tipo, tamanho e SHA-256 no SQLite.

## Modelos e Faster Whisper

`ModelManager` suporta somente a lista multilíngue aprovada. Listagem e verificação não
usam rede. Download só ocorre por comando explícito com `--confirm`, primeiro em
diretório temporário sob `RuntimePaths.models` e depois no destino final verificado.

Uma transcrição comum exige que o modelo já esteja instalado. `FasterWhisperEngine` abre
o diretório local com `local_files_only=True`, impedindo download implícito. A integração
validada usa Faster Whisper 1.2.1, CTranslate2 4.8.2 e PyAV 16.1.0.

## Perfis de execução

- `cpu`: seleciona CPU com `int8`.
- `cuda`: exige dispositivo e runtime aprovados, usa `int8_float16` e nunca faz fallback.
- `auto`: prefere CUDA somente após a sondagem; caso contrário usa CPU `int8` e registra
  o motivo.

No Windows, a sondagem verifica CTranslate2 e as bibliotecas necessárias. A presença da
GPU não prova disponibilidade de CUDA/cuDNN. Para os runtimes oficiais CUDA 12/cuBLAS 12 e
cuDNN 9 instalados pelo operador, a aplicação registra apenas no processo atual os
diretórios padrão da NVIDIA com `os.add_dll_directory`, antes da importação de CTranslate2.
Ela não altera `PATH` global nem aceita diretórios arbitrários. A 7B confirmou
`int8_float16` em CUDA com Faster Whisper 1.2.1 e CTranslate2 4.8.2; CPU `int8` continua
o caminho seguro quando a sondagem não aprovar CUDA.

## Abstração e serviço de transcrição

`TranscriptionEngine` é um `Protocol` que desacopla o domínio do backend. O adaptador
`FasterWhisperEngine` recebe mídia e modelo controlados, aplica idioma, beam size,
timestamps por palavra e VAD, consome integralmente o iterador lazy e converte a saída
em `Segment`, `Word`, idioma detectado e probabilidade.

`TranscriptionService` coordena o fluxo:

```text
gravação catalogada
  → modelo local verificado
  → perfil resolvido
  → job pending/running
  → engine consome todos os segmentos
  → Transcript + métricas
  → publicação transacional
  → job succeeded
  → exportações gerenciadas
```

O comando síncrono da Etapa 3 continua disponível. Na fila, `TranscriptionQueue` valida
gravação, mídia e modelo local e persiste configurações sem executar inferência. O worker
reivindica um job e chama o mesmo serviço de transcrição.

```text
pending/queued
  → reivindicação SQLite com compare-and-set
  → running/claiming, com worker e lease
  → loading_model → transcribing → finalizing
  → publicação transacional
  → succeeded/completed
```

Fase, percentual, segundos processados, duração total e eventos sobrevivem a novos
processos. O percentual permanece abaixo de 100% até a publicação final.

A transcrição, seus segmentos e palavras e a mudança do job para `succeeded` são
publicados na mesma transação. Falhas não publicam resultado parcial; o job recebe
`failed` com erro técnico sanitizado. Uma queda abrupta entre filesystem e SQLite ainda
pode exigir reconciliação futura.

### Concorrência, leases e recuperação

A reivindicação usa `BEGIN IMMEDIATE` e um `UPDATE` condicionado ao estado `pending`.
Antes de adquirir esse lock de escrita, o worker faz uma consulta somente leitura por job
pendente reivindicável ou lease vencida. Resultado vazio encerra o polling sem transação de
escrita; um falso negativo causado por criação concorrente é revisto no polling seguinte.
Quando existe candidato, recuperação e seleção são repetidas dentro da transação imediata,
de modo que a pré-consulta nunca substitui o compare-and-set nem decide a posse.

Cada worker processa no máximo um job por vez; uma heartbeat renova a lease durante
operações demoradas. `SQLITE_BUSY` e `SQLITE_LOCKED` na consulta ou reivindicação recebem
espera curta, responsiva ao shutdown, e no máximo três retries consecutivos. Um sucesso
zera a contagem. Erros SQLite permanentes e falhas transitórias além do limite encerram o
controlador com a exceção registrada e logada, em vez de serem ocultados em loop infinito.
Isso é prevenção de starvation; o `busy_timeout` permanece uma espera do SQLite quando já
existe contenção e não eliminaria a aquisição desnecessária de locks pelo polling vazio.

Falhas SQLite transitórias da heartbeat também são repetidas de modo limitado enquanto há
margem segura antes da expiração. A primeira falha permanece observável no estado da
heartbeat; perda definitiva ou impossibilidade de renovar com segurança ativa um sinal
compartilhado, consultado nos callbacks de progresso e nos pontos cooperativos.

`LeaseOwnershipLost` separa perda de posse de falha do engine. Renovação, progresso,
cancelamento pelo worker, falha e publicação exigem status `running`, o mesmo worker e
lease ainda válida. Um worker obsoleto abandona a tentativa local sem alterar o job que
outro worker recuperou, e o loop permanece apto a reivindicar trabalhos seguintes.

Se uma exclusão concorrente ou outra anomalia tornar indisponível um job já reivindicado,
o serviço e o repositório convertem a ausência em `LeaseOwnershipLost`. O worker retorna
ao loop sem asserção de existência; a política normal de exclusão impede esse caso para
jobs pendentes ou em execução e a API responde conflito em vez de remover o estado ativo.

Leases expiradas seguem política determinística: cancelamento pendente termina como
`cancelled`; limite de tentativas atingido termina como `failed`; os demais jobs voltam a
`pending` e podem reiniciar desde o começo. Como não existe retomada acústica, a execução
é `at least once`, não “exactly once”. Somente um worker possui a lease válida e somente
o proprietário atual pode persistir progresso ou publicar. Depois da expiração pode
existir uma pequena sobreposição de computação até o worker obsoleto alcançar um ponto
cooperativo; a restrição única por job e a publicação transacional impedem duas
publicações finais.

O cancelamento em execução é cooperativo e verificado durante o consumo lazy e antes da
publicação. Ele pode aguardar carregamento do modelo ou outra operação indivisível.
`KeyboardInterrupt` e `SystemExit` encerram o worker sem classificação como falha normal;
a lease expirada permite recuperação posterior. Não existe timeout total padrão.

## CLI

O entrypoint oferece:

- `config check`;
- `subjects add|list`;
- `recordings import|list|delete`;
- `models list|check|download`;
- `transcribe`;
- `jobs enqueue|list|show|cancel|retry`;
- `worker run [--once]`;
- `transcripts list|show`;
- `export` para TXT, Markdown, SRT, WebVTT e JSON;
- `serve [--host 127.0.0.1] [--port 8765] [--workers 1]`;
- `--help` e `--version`.

A CLI compõe `MediaLibrary`, `Repository`, `ModelManager`, `TranscriptionService` e
`TranscriptExporter`; ela não replica suas regras.

## API HTTP local

`local-transcriber serve` inicia FastAPI e Uvicorn em `127.0.0.1:8765` por padrão. O
comando recusa outro host e quantidade de workers diferente de 1. Um lock mantido sob o
runtime também impede que dois processos HTTP consumam a mesma fila, inclusive se forem
iniciados fora do comando recomendado.

Para o uso cotidiano no Windows, `scripts/start-local-transcriber.ps1` chama o mesmo
comando instalado com host `127.0.0.1` e `--workers 1`, mas primeiro verifica a existência
do ambiente virtual e se a porta está em escuta. Ele não instala dependências, não baixa
modelos e não inicia o navegador ou outro processo em segundo plano. O operador encerra o
processo supervisionado com `Ctrl+C`.

Os contratos ficam sob `/api` e incluem saúde, versão, capacidades, matérias, gravações,
pesquisa FTS5, modelos instalados, runtime, jobs, transcrições, segmentos, palavras,
exportações, mídia, eventos e sumarização estruturada (`GET|POST /api/transcripts/{id}/summary`,
progresso e download nos formatos Markdown e JSON). A especificação OpenAPI JSON local fica em
`/api/openapi.json`. Swagger UI, ReDoc e outros visualizadores HTML não são expostos,
porque a versão padrão dependeria de CDN e conflitaria com a operação offline. Os modelos
de resposta omitem caminhos físicos, caminho relativo interno da mídia, identificador do
worker e lease.

Uploads usam `multipart/form-data`. O parser entrega um arquivo temporário em spool e a
biblioteca o copia em blocos para o runtime, aplicando limite de tamanho, sanitização do
nome, verificação de Content-Type, extensão, contêiner, stream de áudio e decodificação.
A verificação de Content-Type é uma barreira adicional; a aceitação nunca depende apenas
do valor declarado ou da extensão. A API recebe bytes e metadados, nunca um caminho do
cliente.

Toda transcrição criada pela API entra primeiro na fila. O worker integrado ao lifespan
é uma thread controlada, sequencial e usa os mesmos leases e publicação transacional da
Etapa 4. Encerrar a aplicação impede novas reivindicações e aguarda a operação corrente;
desconectar uma requisição ou SSE não cancela o job. Downloads de modelo continuam
exclusivos da CLI explícita e a API somente informa o comando necessário.

Mídia é resolvida internamente pelo ID da gravação e suporta uma faixa de bytes por
requisição, com `Accept-Ranges`, `Content-Range`, 206 e 416. Exportações são resolvidas por
ID de artefato e entregues como anexos; nenhum endpoint resolve caminhos fornecidos pelo
cliente.

### Segurança HTTP

- bind suportado somente em `127.0.0.1`;
- `Host` limitado a loopback/localhost e `Origin` HTTP local validado em mutações;
- nenhum CORS wildcard;
- erros de domínio sanitizados e erros internos sem stack trace;
- `nosniff`, bloqueio de frames, política de referrer, CSP restritiva e `no-store`;
- contratos OpenAPI sem exemplos de dados pessoais;
- um consumidor de fila por runtime.

### SSE persistente

`GET /api/jobs/{job_id}/events` transmite `text/event-stream`. O campo `id` é a sequência
monotônica persistida do evento dentro do job. `Last-Event-ID` reproduz somente sequências
posteriores. Os tipos expostos são `state`, `phase`, `progress`, `failure`, `cancellation`
e `completion`; comentários de heartbeat mantêm conexões ociosas observáveis.

Respostas de job incluem `last_event_sequence`, obtido por consulta agregada e
parametrizada para o próprio job. A consulta ocorre antes da atualização do snapshot:
uma corrida pode reapresentar um evento, que o cliente rejeita pelo ID, mas nunca avançar
o cursor além do estado representado e perder um terminal. O endpoint aceita ainda
`after_sequence`; quando também existe `Last-Event-ID`, usa o maior cursor sem quebrar
consumidores anteriores.

Cada consulta de eventos filtra `job_id` e `sequence > after_sequence`, ordena por
sequência e aplica um limite parametrizado. O comportamento sem cursor continua retornando
todo o histórico para consumidores existentes, mas o SSE sempre usa cursor e lote. Um
backlog é drenado imediatamente em lotes; o intervalo de polling só ocorre depois que uma
consulta não encontra evento novo.

Ao observar estado terminal após uma consulta vazia, uma confirmação incremental cobre a
corrida em que a transição poderia ocorrer entre a consulta e a leitura do job. Não há
conexão nem transação aberta durante a espera. O stream termina após entregar o evento
terminal, e a perda do cliente apenas encerra o produtor HTTP.

## Interface web local

A raiz `/` entrega `index.html`, e `/assets` serve CSS e módulos JavaScript empacotados
com a distribuição Python. A interface e a API compartilham a mesma origem; não existe
etapa obrigatória de build, runtime Node, CDN, telemetria ou chamada a serviço externo.
As rotas `/api/docs` e `/redoc` permanecem ausentes, enquanto `/api/openapi.json` continua
disponível como especificação local dos contratos.

O shell usa HTML semântico com navegação compacta e vistas para painel, matérias,
biblioteca, fila, leitura e modelos. O painel reúne saúde do serviço, estado real da thread
do worker, perfil recomendado, disponibilidade do modelo e jobs recentes. Matérias podem
ser criadas e usadas como filtro da biblioteca. Upload, pesquisa e exclusão usam os
contratos existentes, sem aceitar caminhos do cliente.

Antes de enfileirar, um diálogo reúne modelo, idioma, perfil, beam size, VAD e timestamps
por palavra, exibe impedimentos e exige confirmação. A interface nunca inicia download de
modelo; quando ele falta, mostra o comando explícito da CLI. Jobs são reconstruídos do
SQLite após recarga, e cada job não terminal recebe um `EventSource`. O navegador preserva
o último ID entregue na reconexão nativa, enquanto o backend garante replay persistente.
Estados de desconexão e recuperação são anunciados sem cancelar o trabalho.

Requisições de carga global, pesquisa e leitura usam gerações monotônicas e
`AbortController`. Depois de cada espera assíncrona, o contexto é validado antes de
alterar estado, DOM ou mensagens; respostas e falhas de seleções antigas são descartadas.
Exportações mantêm escopo próprio por transcrição e formato: o download usa o ID do
artefato efetivamente solicitado, mas controles e avisos só são atualizados se a leitura
original ainda estiver ativa.

Um rastreador independente por job preserva a última sequência SSE aceita. O frontend
abre o stream a partir do cursor do snapshot e rejeita IDs inválidos, repetidos, menores,
fora de ordem ou divergentes do payload. Gerações de listener descartam callbacks tardios
após fechamento; jobs simultâneos não compartilham cursor e o estado é removido quando o
job deixa o snapshot da biblioteca.

A leitura usa o endpoint controlado de mídia, aceita seek por timestamps clicáveis e
apresenta texto integral, idioma, métricas, segmentos e probabilidades somente quando
existem. Ela integra também o painel de síntese pedagógica com Ollama local (tese central,
resumo executivo, roteiro falado com cópia, glossário com sincronização de timestamps no player,
flashcards interativos e download direto de resumos em Markdown e JSON). Exportações nos cinco
formatos podem ser criadas e baixadas pelos IDs gerenciados. O suporte concreto de reprodução ainda
depende dos codecs do navegador.

Dados recebidos da API são inseridos com `textContent`, atributos controlados e criação
explícita de elementos. A implementação não usa `innerHTML`, `outerHTML`,
`insertAdjacentHTML`, `document.write` ou `eval`. O CSP permite somente recursos da mesma
origem necessários a scripts, estilos, mídia e requisições e mantém objetos, frames e base
externa bloqueados.

Acessibilidade inclui landmarks, link para pular ao conteúdo, labels associados, foco
visível, navegação por teclado, diálogos nativos, regiões `aria-live`, texto além da cor e
redução de movimento. O layout foi validado em 1366×768 e em viewport estreita, sem
overflow horizontal da página.

## Evidência de validação

### Automatizada e com doubles

Historicamente, a baseline consolidada incluiu 115 testes Python e 11 testes JavaScript
comportamentais funcionais sem GPU, modelo ou rede. Essa base cobre configuração, domínio,
migrações v1–v4, mídia sintética, pesquisa, exportadores, perfis, ausência de download
automático, backend injetado, consumo lazy, reivindicação concorrente, leases, recuperação,
cancelamento, retry, progresso, publicação idempotente, falhas transacionais, recuperação
do heartbeat após erro SQLite transitório, perda definitiva de posse, bloqueio de worker
obsoleto, continuidade do loop, áudio longo simulado, comandos principais da CLI, contratos
HTTP, upload, limites, Host/Origin, fila, SSE, replay, heartbeat, desconexão, Range,
exportações, OpenAPI offline, ausência das rotas de documentação HTML, consultas
incrementais limitadas, backlog em vários lotes, lifespan, shell e assets locais, HTML
semântico, ausência de sinks inseguros, fluxo web de upload, pesquisa, fila, cancelamento,
reprodução por Range, exportações e metadados de runtime. Promessas e respostas controladas
cobrem cargas globais fora de ordem, leituras e pesquisas concorrentes, exportação durante
troca de leitura, erros obsoletos, duplicação e regressão SSE, replay inicial, reconexão,
listener encerrado e jobs simultâneos. Esses testes validam comportamento determinístico,
não qualidade de inferência.

Com a conclusão da Etapa 8 e a manutenção da Etapa 8B, a suíte de testes Python foi expandida
para 141 testes (adicionando 26 testes para o módulo e as rotas de sumarização estruturada
utilizando mocks e fixtures locais, sem garantia de rede monitorada no nível do sistema operacional).
Os 11 testes JavaScript comportamentais históricos não foram reexecutados nesta intervenção de
manutenção; em seu lugar, a verificação estática de JavaScript foi realizada pela execução
individual de `node --check` em cada um dos 4 arquivos JS da aplicação web, todos concluídos com
código de saída 0. A validação de baseline registrou 10 advertências pré-existentes de Ruff E501
e 4 arquivos com diferenças de formatação mantidos inalterados nos oito arquivos restritos da etapa,
além de uma falha inicial seguida de retries efetivos em teste intermitente de retries de heartbeat.

As regressões 5C verificam que fila vazia não abre transação imediata, upload concorre com
polling ocioso sem locks de escritor, um job criado após pré-consulta vazia é encontrado no
polling seguinte, falha transitória não mata o controlador e retries repetidos são
limitados. Os testes existentes continuam cobrindo dois workers, lease expirada, ciclo
completo com engine falsa e evento terminal sanitizado. Nenhuma inferência real foi usada.

Uma inspeção real em navegador Chromium percorreu painel, biblioteca vazia e preenchida,
modelo ausente, confirmação, falha, job em andamento, busca, leitura, exportação, tela
estreita, foco por teclado e reconexão SSE. A validação complementar atrasou de forma
controlada a leitura e a pesquisa A, abriu B logo depois e confirmou que A não reapareceu;
também interrompeu e reiniciou o servidor local para observar desconexão e reconexão SSE
sem erro no console. Foram usados apenas runtime e conteúdo sintéticos temporários; não
houve download de modelo nem inferência sobre áudio pessoal.

### Execução real

As validações 3B, 3C e 7 executaram três gravações curtas em português com o modelo `small`
multilíngue, CPU `int8`, VAD e timestamps por palavra. A Etapa 7 também percorreu upload
local, fila HTTP, worker integrado, eventos SSE, busca FTS5, leitura web, mídia por Range e
os cinco formatos de exportação. A primeira execução registrou RTF 1,612. A segunda
registrou RTF 0,4778, aproximadamente 2,09 vezes mais rápida que tempo real, com pico
aproximado de working set de 709,9 MiB. A terceira registrou RTF aproximado de 0,816 em
18,23 segundos de mídia e 14,88 segundos de processamento persistido. Caches, aquecimento,
conteúdo e duração podem influenciar essas diferenças.

Na segunda execução, a estrutura temporal e os números principais foram validados, mas
houve erros em vocabulário técnico específico. Nenhuma das amostras possuía gabarito
textual independente, portanto nenhuma taxa de precisão foi calculada. Nenhum defeito de
implementação foi identificado.

A Etapa 7 confirma o caminho feliz integrado, mas não caracteriza desempenho de carga longa,
precisão textual, matriz ampla de formatos ou cancelamento/retry/recuperação com inferência
real. A 7B acrescentou uma comparação controlada com `small`: 33,97 s de mídia levaram
aproximadamente 118,32 s em CPU `int8` (RTF 3,482) e 19,79 s em CUDA `int8_float16`
(RTF 0,583), incluindo carregamento. A amostra não gerou segmentos ou palavras e não mede
qualidade de fala; o operador relatou testes posteriores de áudio em CUDA, sem telemetria
registrada por esta entrega. Um RTF de amostra não é projeção confiável de gravação longa.

Em observação operacional posterior, um reinício do computador durante uma transcrição foi
seguido de nova inicialização do serviço; a fila recuperou o job persistido e ele concluiu.
Isso confirma a recuperação ponta a ponta do estado, mas não caracteriza latência de lease,
cancelamento ou desempenho de carga longa.

A Etapa 4 não executou inferência real. Fila, heartbeat, expiração, cancelamento e
recuperação foram validados com engine falso e relógio injetável. O áudio simulado de duas
horas confirma ausência de timeout artificial no domínio, não desempenho de carga longa.

## Limitações e trabalho futuro

- codecs concretos dependem do PyAV/FFmpeg instalado;
- duplicidade é somente por bytes;
- não há conversão ou normalização de mídia;
- recuperação após crash pode reiniciar toda a inferência e aguarda expiração da lease;
- cancelamento pode não ser instantâneo em operações indivisíveis;
- pesquisa não possui ranking ou filtros avançados;
- reexportação do mesmo formato exige gestão explícita;
- qualidade foi observada sem gabarito independente, e vocabulário técnico específico
  ainda pode apresentar erros;
- qualquer adaptação contextual futura exige escopo próprio e avaliação com gabarito;
- CUDA foi validada somente com `small` e amostra curta; modelos maiores, duração longa,
  estabilidade térmica e qualidade textual continuam sem caracterização;
- reprodução no navegador depende dos codecs disponíveis;
- a seleção atual da leitura não persiste após recarregar a página;
- shutdown pode aguardar uma operação indivisível do engine;
- SSE detecta eventos por consultas SQLite curtas e possui pequena latência de entrega;
- diarização, microfone ao vivo e Home Assistant permanecem fora do MVP; a sumarização com Ollama local opera exclusivamente em localhost, com suporte opt-in a ChatGPT via plano do usuário.

Consulte [estado atual](PROJECT_STATE.md), [decisões](DECISIONS.md),
[problemas conhecidos](KNOWN_ISSUES.md), [roadmap](ROADMAP.md) e os relatórios
[Etapa 1](PHASE_01_FOUNDATION.md), [Etapa 2](PHASE_02_MEDIA_LIBRARY.md),
[Etapa 3](PHASE_03_WHISPER_AND_CLI.md), [validação 3B](PHASE_03B_REAL_VALIDATION.md),
[validação 3C](PHASE_03C_SECOND_REAL_VALIDATION.md) e
[Etapa 4](PHASE_04_PERSISTENT_QUEUE.md) e
[correção complementar 4B](PHASE_04B_LEASE_RELIABILITY.md),
[Etapa 5](PHASE_05_LOCAL_API_AND_SSE.md),
[correção complementar 5B](PHASE_05B_OFFLINE_DOCS_AND_INCREMENTAL_SSE.md) e
[Etapa 6](PHASE_06_WEB_INTERFACE.md) e
[correção complementar 5C](PHASE_05C_SQLITE_CONTENTION_RELIABILITY.md) e
[correção complementar 6B](PHASE_06B_ASYNC_CONCURRENCY_RELIABILITY.md),
[Etapa 7](PHASE_07_MVP_INTEGRATION_AND_REAL_VALIDATION.md),
[correção complementar 7B](PHASE_07B_LOCAL_CUDA_ACCELERATION.md),
[Etapa 8](PHASE_08_STRUCTURED_SUMMARIZER_AND_WEB_INTEGRATION.md) e
[manutenção e validação de baseline 8B](PHASE_08B_MAINTENANCE_VALIDATION_2026-10-05.md) e
[Etapa 8I](PHASE_08I_SIGN_IN_WITH_CHATGPT_SUMMARIZER_2026-10-24.md).

## Manutenção 8C (2026-10-05)

142 testes Python aprovados no checkout isolado; Ruff check global aprovado e
28 arquivos com format --check aprovado. AST funcional preservada nos quatro
arquivos de estilo (três docstrings de testes apenas refluídas). Teste de retries
usa FakeClock estável; regressão separada avança o relógio e prova perda de lease
antes de retry inseguro. O código de produção da fila não mudou. Resultados 8B
acima são históricos; as pendências de estilo foram resolvidas na 8C.
Compilação de sintaxe e diff-check aprovados; pip check sem dependências quebradas,
com aviso de distribuição inválida no ambiente existente, não reparado.
Sem inferência real, modelos, mídia pessoal ou download nesta manutenção.
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

## Etapa 8I: Síntese Estruturada com Sign in with ChatGPT (2026-10-24)

Opção opt-in de resumo estruturado temporal via Sign in with ChatGPT e plano do usuário,
mantendo Ollama local (`qwen2.5:3b`) como motor padrão 100% offline do Local Transcriber.
- Transporte desacoplado via interface `LLMTransport` (`OllamaTransport` e `ChatGPTTransport`).
- Autenticação OAuth 2.0 PKCE S256 / OIDC oficial (`https://auth.openai.com/api/accounts/authorize`,
  escopos `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`,
  recurso `https://api.openai.com/v1`, e `ext_agent_host_id` estável).
- Registro dinâmico de cliente: `client_id` emitido na primeira inscrição é preservado
  em arquivo protegido `client_id.txt` para reautorizações; reautorização omite `agent_name_hint`
  e inclui `id_token_hint` da conta salva.
- Callback loopback HTTP restrito estritamente a `127.0.0.1` (`localhost` rejeitado per SIWC spec).
- Validação mandatória de `state` (inclusive em erros) com TTL de 10 minutos para autorizações pendentes.
- Escape HTML rigoroso de mensagens de erro e emails para prevenção contra XSS.
- Armazenamento de tokens com ACL restrita nativa NTFS no Windows via `icacls` (falha fechada);
  chmod restrito apenas em plataformas POSIX.
- Validação mandatória de ID token RS256/JWKS e escopos concedidos antes de salvar credenciais.
- Catálogo `/v1/models` inspeciona array `models` com `slug` e `visibility`, exigindo `gpt-6-luna`.
- Streaming SSE via `/v1/responses` consumindo `response.output_text.delta` e prevenindo
  duplicação textual em eventos posteriores `output_item.done` e `response.completed`.
- Totalmente validado com testes unitários/integração determinísticos (186 testes na suíte).
- [Relatório da Etapa 8I](PHASE_08I_SIGN_IN_WITH_CHATGPT_SUMMARIZER_2026-10-24.md).

## Etapa 8J-A: Gateway Privado FastAPI em Loopback para Ingestão Remota (2026-10-24)

Gateway FastAPI dedicado (`remote_gateway.py`), desativado por padrão (configuração em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.json`) e com binding restrito ao loopback `127.0.0.1` (porta padrão `8766`, configurável na CLI), projetado para ingestão segura de áudio e acompanhamento de jobs a partir de dispositivos remotos autorizados (ex.: iPad via Tailscale) sem expor a API core ou a máquina local:
- **Separação de limites**: aplicação FastAPI independente (`remote_gateway.py`), executada em porta distinta (padrão `8766`, configurável via CLI, sempre em `127.0.0.1`), sob o prefixo `/remote/v1`, isolada da core API (`8765`). Rotas internas, documentação interativa (Swagger/ReDoc), CORS e endpoints de sumarização permanecem completamente inacessíveis pelo gateway.
- **Identidade e Proxy Confiável**: validação estrita do cabeçalho de identidade (`Tailscale-User-Login`) injetado pelo proxy reverso local de confiança. Cabeçalho ausente ou vazio resulta em 401; cabeçalho duplicado ou identidade não autorizada resulta em 403; requisições com `Tailscale-Funnel-Request` são rejeitadas com 403. Uvicorn executa com `proxy_headers=False` e `server_header=False`. Binding público rejeitado (403) no nível do middleware HTTP.
- **Proteção CSRF e Origem**: exigência mandatória de correspondência de `Host` (bare hostname estritamente em allowlist, rejeitando porta, path, query, fragment ou userinfo) e `Origin` HTTPS exato (sem barra final ou porta inesperada); sessão com cookie contendo `session_id` aleatório (`SameSite=Strict`, `HttpOnly`, `Secure` no caminho `/remote/v1`) e token CSRF assinado por HMAC-SHA256 vinculado à sessão e à identidade, derivado de segredo `%LOCALAPPDATA%\LocalTranscriber\remote\csrf.key` com ACL restrita do Windows (`icacls`), validada e reaplicada no startup.
- **Mitigação de IDOR**: banco de estado SQLite dedicado (`%LOCALAPPDATA%\LocalTranscriber\remote\gateway.sqlite3`), preservando o schema v4 do core database. Gravações e jobs são indexados pela chave HMAC da identidade; associação de um `recording_id` completado a identidades distintas é expressamente proibida (inclusive via índice parcial UNIQUE em banco).
- **Defesa de I/O, Streaming e Concorrência**: cabeçalho `Content-Length` obrigatório (411 se ausente ou chunked); contagem estrita de bytes recebidos durante o streaming abortando com 413 caso exceda o tamanho declarado ou `max_upload_bytes`; timeout total da recepção do corpo (`request_timeout_seconds`, padrão 600s); checagem preventiva de espaço em disco (`min_free_disk_bytes`) com lock de upload serializando requisições no processo gateway contra concorrência TOCTOU (concorrência com importações simultâneas locais no core não medida em hardware real); captura de `DuplicateMediaError` ou colisões de integridade SHA-256 no core retornando 409 sanitizado; limpeza de arquivos `.part` órfãos.
- **Idempotência Transacional e Falha Fechada**: suporte a `Idempotency-Key` no upload e na criação de jobs; `claim_upload` em estado `importing` recente retorna 409 busy; após crash ou expiração de claim em `importing`, caso a mídia já exista no core, a requisição falha fechada com 409 sanitizado para impedir IDOR entre identidades distintas (dada a impossibilidade de provar posse retrospectiva sem alteração estrutural no schema v4 do core). Exclusão de gravação no core resulta em 410 no agendamento de jobs, liberando a claim transacionalmente.
- **CLI**: comando `local-transcriber remote-gateway serve --host 127.0.0.1 --port 8766`.
- **Validação Sintética**: 83 testes sintéticos dedicados (e 63 regressões do core) cobrindo os contratos de segurança definidos, limites de concorrência, ciclo de vida de upload e job, recuperação de falhas e sanitização de logs. A suíte determinística com a fixture de socket compatível com Windows assegura operação offline completa.
- **Portão de Segurança Futuro**: a segurança física em rede real depende do provisionamento e autenticação do proxy privado (ex.: Tailscale), o qual não foi ativado nem exposto publicamente nesta etapa.

## Etapa 8J — Etapa 1: Sessão Privada Temporária e Orquestração Tailscale Serve (2026-10-25)

Ciclo de vida de sessão temporária controlada pelo usuário via CLI ou launcher local, orquestrando o proxy reverso Tailscale Serve e o gateway privado em loopback com garantia de reversão seletiva e fail-closed:
- **Separação Arquitetural do Core**: o Core API permanece estritamente na porta loopback `8765`, executando o único worker sequencial de transcrição. O gerenciador de sessão remota nunca instancia um segundo worker nem toma posse do core server.
- **Plano de Controle Local**: operações de sessão (`remote-session start/status/stop`) operam estritamente no terminal do notebook e nunca são expostas através do gateway ou Tailscale.
- **Encapsulamento do Tailscale Serve**: o cliente `TailscaleCli` descobre o executável local, valida o status conectado e ativa o proxy reverso pontual (`tailscale serve --bg --https=443 http://127.0.0.1:8766`). O Tailscale Funnel é terminantemente proibido. Ao encerrar a sessão, executa exclusivamente a desativação do mapeamento (`tailscale serve --https=443 off`), sendo proibido o uso de comandos globais destrutivos como `tailscale serve reset` ou `tailscale down`.
- **Verificação Fail-Closed de Propriedade de Processo (`ProcessVerifier`)**: para mitigar o risco de reciclagem de PID pelo sistema operacional, o término de processos exige validação cruzada do timestamp de criação (`GetProcessTimes` no Windows) e argumentos da linha de comando contendo o marcador da sessão (`--session-id=<uuid>`). Em caso de dúvida ou conflito, a operação falha de forma fechada sem afetar processos alheios.
- **Recuperação na Inicialização**: `remote/session.json` registra `prepared` antes do spawn, `gateway` após identificar o processo, `activating` antes do Serve e `active` após verificar o mapping. Gravação temporária com flush/fsync e replace antecede os efeitos. Falhas revertem seletivamente; se a rede, a posse ou o rollback forem incertos, o journal e temporários necessários permanecem.
- **Preservação de Jobs e Serviços**: o encerramento da sessão remota preserva integralmente o Core API em execução e quaisquer jobs da fila SQLite (em andamento, pendentes ou concluídos).
- **Validação e Testes**: 101 testes de sessão; runners/processos sintéticos, callbacks ctypes com HANDLE de 64 bits e exclusão concorrente com trava real do SO. São 194 testes focados com CLI/gateway. Nenhuma execução real de Tailscale ou dispositivo móvel.
- **Documentação de Referência**: plano de evolução contratado em `docs/REMOTE_ACCESS_INTEGRATION_PLAN.md`, relatório técnico em `docs/PHASE_08J_STAGE1_REMOTE_SESSION_2026-10-25.md` e relatório de blindagem em `docs/PHASE_08J_STAGE1_HARDENING_2026-10-25.md`.

### Hardening Pré-Gate da Sessão Remota (Etapa 0 - 2026-10-25)
- **Tipagem Win32 64-bit e Fail-Closed Rigoroso**: `ProcessVerifier` declara tipos Win32 formais (`wintypes.HANDLE`, `wintypes.BOOL`, `wintypes.DWORD`, `wintypes.LPFILETIME`) prevenindo truncamento de ponteiros de 64 bits. Rejeita metadados nulos e exige conferência exata do token de comando `--session-id` via tokenização `shlex` (recusando meras substrings) e do timestamp de criação.
- **Inspeção Estrita de Serve e Bloqueio de Funnel**: `serve_status` opera com falha fechada para erros de execução e JSON inválido. A inicialização é abortada se o Tailscale Funnel estiver ativo ou se a porta HTTPS já estiver associada a outro backend. O comando `stop` só desativa o proxy se comprovadamente mapeado para o gateway da sessão.
- **Observabilidade Pura em `status`**: a inspeção de status tornou-se estritamente de somente leitura; a ausência de PID não desativa proxies nem remove arquivos de sessão.
- **Transacionalidade e Recuperação em `stop`**: o journal só é removido após confirmar ausência do mapping e término do processo. Erros de consulta, off, leitura posterior ou terminação preservam recuperação; a limpeza stale usa o mesmo protocolo, sem ignorar erros.
- **Serialização Concorrente**: context manager `_session_lock` (`.session.lock`) protege execuções paralelas de `start` e `stop`.
- **Sonda de Prontidão Autenticada**: endpoint minimalista `GET /remote/v1/health` valida inicialização do gateway no loopback sob cabeçalhos autenticados de identidade e host, sem expor dados internos nem permitir bypass de segurança.
- **Entrypoint Modular do CLI**: adicionada cláusula `if __name__ == '__main__': sys.exit(main())` garantindo execução de subprocessos filhos com `python -m local_transcriber.cli`.

### Complemento posterior de recuperação (2026-10-25)

A prova de posse de Serve exige TCP HTTPS exclusivo e exatamente um host DNS da sessão,
uma rota raiz e um handler Proxy exato. Estruturas inválidas/desconhecidas, serviços,
TCP forwarding, conteúdo estático, múltiplos hosts e rotas são recusados; ausência de
Proxy não prova porta livre. Portas distintas são preservadas. Resposta vazia ou JSON
não objeto não prova ausência de configuração. Após off, uma nova consulta confirma
o resultado antes de limpar o journal.

Se o processo controlador cair entre spawn e persistência do PID, `prepared` conserva
o marcador, mas exige reconciliação manual sem matar PIDs por suposição. Estado
corrompido e temporário sem journal também bloqueiam mutações. A trava serializa os
comandos desta aplicação; não é transação/CAS com outros clientes Tailscale nem prova
de durabilidade em queda de energia. Não alterar Serve por outro cliente durante a sessão.
Gate aguardando revisão independente; [relatório posterior](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md).


## Ferramentas do agente (2026-10-25)

Os MCPs s?o ferramentas do agente e n?o integram o runtime do transcritor. O filesystem usa `@modelcontextprotocol/server-filesystem@2.0.1`, com diret?rio de trabalho e raiz permitida fixados no projeto. `scripts/start-github-mcp.ps1` consulta a credencial existente do GitHub CLI e inicia `mcp-remote@0.15.2` contra o servidor oficial do GitHub, passando a autoriza??o por vari?vel de ambiente apenas ao processo filho. A configura??o local cont?m caminhos espec?ficos da m?quina; ajuste-os ao mover o checkout.


## Integra??o MCP Graphify (2026-10-25)

Graphify usa graphify-mcp por stdio, com execut?vel e grafo em caminhos absolutos na configura??o local do agente. O extra MCP foi instalado no ambiente pipx existente de graphifyy 0.9.92, sem depend?ncia nova no runtime. A consulta l? o grafo salvo; n?o executa reconstru??o autom?tica nem usa Graphify Cloud. As ferramentas de PR do Graphify podem consultar GitHub via gh; n?o foram usadas nesta valida??o.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.


## Serena e leitura simbólica (2026-10-25)

Serena é ferramenta MCP de desenvolvimento isolada via pipx, fora da `.venv` e
das dependências do aplicativo. A configuração do agente fica em `.codex/config.toml`.
Graphify recupera relações do grafo salvo; Serena consulta símbolos no código atual.
O fluxo deve limitar leitura ao símbolo necessário, sem carregar módulos grandes
inteiros. Evidência e limites no [relatório](PHASE_TOOLING_SERENA_MCP_2026-10-25.md).
