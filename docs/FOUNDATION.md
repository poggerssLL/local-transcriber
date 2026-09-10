# Arquitetura técnica do Local Transcriber

> Documento vivo e cumulativo da arquitetura atual. Os relatórios `PHASE_XX_*.md`
> preservam o estado histórico de cada etapa; esta visão deve acompanhar o sistema.

## Finalidade e estado

O **Local Transcriber** é uma aplicação local para catalogar gravações, executar
transcrição com Faster Whisper e exportar resultados estruturados sem depender de APIs
de IA em nuvem. A versão atual é `0.5.1`, usa schema SQLite v4 e concluiu:

1. fundação e persistência;
2. biblioteca de mídia, pesquisa e exportadores;
3. Faster Whisper, modelos explícitos e CLI;
4. fila persistente e worker local;
5. API FastAPI local e eventos SSE persistentes.

A próxima etapa planejada é a interface web vanilla. Diarização, Ollama, microfone ao
vivo e Home Assistant ainda não foram implementados.

## Estrutura do repositório

```text
Local Transcriber/
├── AGENTS.md
├── README.md
├── pyproject.toml
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
- `cli.py`: expõe os serviços existentes sem duplicar regras de negócio.

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
GPU não prova disponibilidade de CUDA/cuDNN. As validações reais 3B e 3C validaram apenas
CPU `int8`; CUDA continua sem validação ponta a ponta.

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
Cada worker processa no máximo um job por vez; uma heartbeat renova a lease durante
operações demoradas. Falhas SQLite transitórias são repetidas de modo limitado enquanto
há margem segura antes da expiração. A primeira falha permanece observável no estado da
heartbeat; perda definitiva ou impossibilidade de renovar com segurança ativa um sinal
compartilhado, consultado nos callbacks de progresso e nos pontos cooperativos.

`LeaseOwnershipLost` separa perda de posse de falha do engine. Renovação, progresso,
cancelamento pelo worker, falha e publicação exigem status `running`, o mesmo worker e
lease ainda válida. Um worker obsoleto abandona a tentativa local sem alterar o job que
outro worker recuperou, e o loop permanece apto a reivindicar trabalhos seguintes.

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

Os contratos ficam sob `/api` e incluem saúde, versão, capacidades, matérias, gravações,
pesquisa FTS5, modelos instalados, runtime, jobs, transcrições, segmentos, palavras,
exportações, mídia e eventos. A especificação OpenAPI JSON local fica em
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

Cada consulta de eventos filtra `job_id` e `sequence > after_sequence`, ordena por
sequência e aplica um limite parametrizado. O comportamento sem cursor continua retornando
todo o histórico para consumidores existentes, mas o SSE sempre usa cursor e lote. Um
backlog é drenado imediatamente em lotes; o intervalo de polling só ocorre depois que uma
consulta não encontra evento novo.

Ao observar estado terminal após uma consulta vazia, uma confirmação incremental cobre a
corrida em que a transição poderia ocorrer entre a consulta e a leitura do job. Não há
conexão nem transação aberta durante a espera. O stream termina após entregar o evento
terminal, e a perda do cliente apenas encerra o produtor HTTP.

## Evidência de validação

### Automatizada e com doubles

A suíte de 95 testes funciona sem GPU, modelo ou rede. Ela cobre configuração, domínio,
migrações v1–v4, mídia sintética, pesquisa, exportadores, perfis, ausência de download
automático, backend injetado, consumo lazy, reivindicação concorrente, leases, recuperação,
cancelamento, retry, progresso, publicação idempotente, falhas transacionais, recuperação
do heartbeat após erro SQLite transitório, perda definitiva de posse, bloqueio de worker
obsoleto, continuidade do loop, áudio longo simulado, comandos principais da CLI, contratos
HTTP, upload, limites, Host/Origin, fila, SSE, replay, heartbeat, desconexão, Range,
exportações, OpenAPI offline, ausência das rotas de documentação HTML, consultas
incrementais limitadas, backlog em vários lotes e lifespan. Esses testes validam
comportamento determinístico, não qualidade de inferência.

### Execução real

As validações 3B e 3C executaram duas gravações curtas em português com o modelo `small`
multilíngue, CPU `int8`, VAD e timestamps por palavra. Em ambas, o job concluiu, gerou
segmentos e palavras, persistiu métricas, produziu os cinco formatos e foi recuperado em
novos processos. A primeira execução registrou RTF 1,612. A segunda registrou RTF 0,4778,
aproximadamente 2,09 vezes mais rápida que tempo real, com pico aproximado de working set
de 709,9 MiB. Caches, aquecimento, conteúdo e duração podem influenciar essa diferença.

Na segunda execução, a estrutura temporal e os números principais foram validados, mas
houve erros em vocabulário técnico específico. Nenhuma das amostras possuía gabarito
textual independente, portanto nenhuma taxa de precisão foi calculada. Nenhum defeito de
implementação foi identificado.

Essa evidência não conclui a Etapa 7: duas amostras curtas não garantem desempenho em uma
gravação de 1h40. O RTF 0,4778 projetaria aproximadamente 47,8 minutos para essa duração,
mas não constitui medição real de carga longa. Ainda faltam validação ampla de formatos,
qualidade, desempenho, recuperação operacional e CUDA em configuração compatível.

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
- CUDA não foi validada ponta a ponta;
- interface web ainda não existe;
- shutdown pode aguardar uma operação indivisível do engine;
- SSE detecta eventos por consultas SQLite curtas e possui pequena latência de entrega;
- diarização, Ollama, microfone ao vivo e Home Assistant permanecem fora do MVP.

Consulte [estado atual](PROJECT_STATE.md), [decisões](DECISIONS.md),
[problemas conhecidos](KNOWN_ISSUES.md), [roadmap](ROADMAP.md) e os relatórios
[Etapa 1](PHASE_01_FOUNDATION.md), [Etapa 2](PHASE_02_MEDIA_LIBRARY.md),
[Etapa 3](PHASE_03_WHISPER_AND_CLI.md), [validação 3B](PHASE_03B_REAL_VALIDATION.md),
[validação 3C](PHASE_03C_SECOND_REAL_VALIDATION.md) e
[Etapa 4](PHASE_04_PERSISTENT_QUEUE.md) e
[correção complementar 4B](PHASE_04B_LEASE_RELIABILITY.md).
