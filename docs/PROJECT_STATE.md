# Estado atual do projeto

> Fotografia verificada em 2026-09-11 após a Etapa 7. Atualize este documento ao fim de cada fase;
> não reescreva os relatórios históricos de fases concluídas.

O **Local Transcriber** é uma aplicação local para catalogar gravações e persistir o
ciclo de vida de transcrições. A arquitetura atual é um pacote Python com modelos de
domínio, biblioteca de mídia, engine desacoplado, fila persistente, worker local, CLI,
API FastAPI restrita ao localhost, interface web local, eventos SSE, exportadores determinísticos e
persistência de metadados em SQLite; mídias, modelos e demais dados de runtime ficam fora
do repositório.

- Versão do pacote: `0.7.0`.
- Schema SQLite: v4.
- Etapas concluídas: 1, fundação e persistência; 2, biblioteca de mídia e exportadores;
  3, Faster Whisper, gerenciamento explícito de modelos e CLI; 4, fila persistente;
  5, API HTTP local e SSE; 6, interface web local; 7, integração e validação real do MVP.
- Funcionalidades disponíveis: configuração de runtime, catálogo de matérias e gravações,
  importação e inspeção de mídia por PyAV, duplicidade exata por SHA-256, pesquisa FTS5,
  persistência do domínio, transcrição síncrona, enfileiramento, worker local sequencial,
  progresso e eventos persistentes, cancelamento, retry, recuperação por lease e exportação
  TXT, Markdown, SRT, WebVTT e JSON; API versionada sob `/api`, upload progressivo,
  streaming de mídia com Range, downloads de exportações e replay de eventos SSE por
  `Last-Event-ID`; interface web sem build e sem dependência de CDN para painel,
  matérias, biblioteca, fila, leitura, exportação e modelos; a especificação OpenAPI JSON
  continua local e não existe visualizador HTML dos contratos; um único entrypoint expõe
  esses serviços. Gerações monotônicas, cancelamento de requisições e validação explícita
  do contexto impedem que resultados assíncronos obsoletos substituam a seleção atual. O
  iniciador `scripts/start-local-transcriber.ps1` verifica `.venv` e a porta escolhida,
  mantém o processo em primeiro plano e fixa loopback e um worker.
- Dependências validadas: PyAV 16.1.0, Faster Whisper 1.2.1, CTranslate2 4.8.2,
  FastAPI 0.116.2, Starlette 0.48.0, Uvicorn 0.52.4 e python-multipart 0.0.32.
- Última validação registrada nesta fotografia: suíte automatizada com 108 testes Python e
  11 testes JavaScript comportamentais, e execução real ponta a ponta em uma amostra curta
  controlada. A execução passou por upload local, job HTTP, worker Faster Whisper, eventos
  persistentes, busca FTS5, leitura, Range e cinco exportações, sem rede ou download.
- Commit funcional verificado da Etapa 3: `b28da0480bee08f533a338001284b36e2a6565bc`.
- Próxima etapa: futura Etapa 8, que não foi iniciada nesta entrega.
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
- A sondagem real encontrou um dispositivo CUDA, mas faltaram `cublas64_12.dll` e
  `cudnn_ops64_9.dll`; CUDA permanece sem validação ponta a ponta.
- Fora do MVP atual: diarização, Ollama, microfone ao vivo e Home Assistant.

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
[Etapa 7](PHASE_07_MVP_INTEGRATION_AND_REAL_VALIDATION.md).
