# Decisões arquiteturais

Este arquivo registra por que decisões foram tomadas, para que novas tarefas não
revertam escolhas anteriores sem compreender suas consequências.

## ADR-001 — Operação local

- Data: 2026-09-09
- Status: aceita
- Decisão: operar localmente, sem APIs de IA em nuvem.
- Motivo: preservar privacidade e independência de serviços externos.
- Consequências: processamento e dados permanecem no computador do usuário.

## ADR-002 — Primeiro engine

- Data: 2026-09-09
- Status: aceita
- Decisão: usar Faster Whisper como primeiro engine de transcrição.
- Motivo: é o engine definido pelo contrato para a primeira integração real.
- Consequências: a Etapa 3 deve integrá-lo sem antecipar engines posteriores.

## ADR-003 — Papel do SQLite

- Data: 2026-09-09
- Status: aceita
- Decisão: armazenar no SQLite somente metadados, nunca arquivos grandes como BLOB.
- Motivo: separar o catálogo dos arquivos gerenciados.
- Consequências: o banco referencia caminhos relativos de arquivos no runtime.

## ADR-004 — Runtime fora do repositório

- Data: 2026-09-09
- Status: aceita
- Decisão: manter runtime em `%LOCALAPPDATA%\LocalTranscriber`.
- Motivo: impedir que dados pessoais e artefatos operacionais entrem no código-fonte.
- Consequências: testes e desenvolvimento podem usar um diretório absoluto configurado.

## ADR-005 — Inspeção com PyAV

- Data: 2026-09-09
- Status: aceita
- Decisão: usar PyAV e as bibliotecas FFmpeg de sua distribuição para inspecionar e decodificar mídia.
- Motivo: validar contêiner, stream de áudio e decodificação real.
- Consequências: a disponibilidade de codecs depende do wheel do PyAV instalado.

## ADR-006 — Importação progressiva

- Data: 2026-09-09
- Status: aceita
- Decisão: copiar mídia em blocos para um temporário antes da movimentação atômica.
- Motivo: limitar o uso de memória e validar o arquivo antes de publicá-lo no runtime.
- Consequências: falhas normais limpam temporários e compensam a persistência parcial.

## ADR-007 — Duplicidade exata

- Data: 2026-09-09
- Status: aceita
- Decisão: detectar duplicidade pelo SHA-256 dos bytes.
- Motivo: oferecer uma identidade determinística do conteúdo importado.
- Consequências: arquivos perceptualmente iguais com bytes diferentes não são duplicados.

## ADR-008 — Caminhos relativos controlados

- Data: 2026-09-09
- Status: aceita
- Decisão: persistir apenas caminhos relativos normalizados e confinados ao runtime.
- Motivo: evitar path traversal e não expor caminhos físicos do sistema.
- Consequências: caminhos absolutos, prefixos de unidade, barras invertidas e `..` são rejeitados.

## ADR-009 — Migrações incrementais

- Data: 2026-09-09
- Status: aceita
- Decisão: manter migrações publicadas imutáveis e adicionar versões incrementais.
- Motivo: atualizar bancos existentes sem reescrever seu histórico.
- Consequências: cada mudança estrutural exige nova migração para banco vazio e existente.

## ADR-010 — Pesquisa com FTS5

- Data: 2026-09-09
- Status: aceita
- Decisão: usar SQLite FTS5 para pesquisa textual.
- Motivo: pesquisar título, matéria e transcrição localmente com suporte a Unicode.
- Consequências: triggers mantêm o índice sincronizado; ranking e filtros avançados não existem ainda.

## ADR-011 — Exportadores determinísticos

- Data: 2026-09-09
- Status: aceita
- Decisão: produzir exportações determinísticas em UTF-8 com quebras `LF`.
- Motivo: garantir resultados estáveis e testáveis entre execuções.
- Consequências: formatação, arredondamento de timestamps e escaping seguem regras explícitas.

## ADR-012 — API e interface em fases futuras

- Data: 2026-09-09
- Status: aceita
- Decisão: implementar FastAPI e frontend vanilla somente nas fases previstas.
- Motivo: manter a evolução por etapas definida no roadmap.
- Consequências: FastAPI e SSE entraram na Etapa 5, a interface vanilla entrou na Etapa 6
  e nenhuma delas usa CDN.

## ADR-013 — Downloads explícitos

- Data: 2026-09-09
- Status: aceita
- Decisão: nunca baixar modelos silenciosamente.
- Motivo: manter consumo de rede e armazenamento sob controle do usuário.
- Consequências: qualquer download futuro exigirá ação explícita.

## ADR-014 — Separação do Local AI

- Data: 2026-09-09
- Status: aceita
- Decisão: manter o Local Transcriber completamente separado do repositório `Local AI`.
- Motivo: são projetos e históricos Git distintos.
- Consequências: tarefas deste projeto não usam, modificam nem versionam o repositório irmão.

## ADR-015 — Abstração do engine

- Data: 2026-09-09
- Status: aceita
- Decisão: expor transcrição por um `TranscriptionEngine` estruturalmente tipado e manter
  Faster Whisper em um adaptador.
- Motivo: separar o domínio do backend local e permitir um executor remoto futuro.
- Consequências: a CLI usa `TranscriptionService`; detalhes do Faster Whisper não entram
  na persistência nem na biblioteca de mídia.

## ADR-016 — Modelos explícitos e locais

- Data: 2026-09-09
- Status: aceita
- Decisão: instalar modelos somente pelo comando `models download MODEL --confirm`, sob
  `RuntimePaths.models`, e transcrever apenas com `local_files_only=True`.
- Motivo: impedir downloads silenciosos e manter arquivos grandes fora do Git.
- Consequências: um modelo ausente gera erro acionável antes da criação do job.

## ADR-017 — Perfis de execução conservadores

- Data: 2026-09-09
- Status: aceita
- Decisão: CPU usa `int8`; CUDA usa `int8_float16`; `auto` só escolhe CUDA após sondar
  CTranslate2 e as bibliotecas CUDA/cuDNN exigidas.
- Motivo: a presença da GPU não comprova que o runtime de inferência está completo.
- Consequências: `auto` relata o motivo do fallback; CUDA explícita nunca faz fallback.

## ADR-018 — Publicação transacional

- Data: 2026-09-09
- Status: aceita
- Decisão: consumir integralmente os segmentos lazy antes de publicar e inserir a
  transcrição junto da transição do job para `succeeded` na mesma transação SQLite.
- Motivo: impedir que falhas publiquem resultados parciais como concluídos.
- Consequências: falhas deixam o job como `failed`, com mensagem técnica sanitizada e sem
  uma transcrição parcial persistida.

## ADR-019 — CLI com argparse

- Data: 2026-09-09
- Status: aceita
- Decisão: usar um único entrypoint `local-transcriber`, implementado com `argparse`.
- Motivo: oferecer operação completa sem adicionar outro framework de CLI.
- Consequências: comandos chamam repositório, biblioteca, exportador e serviço existentes.

## ADR-020 — Documentação viva e histórico imutável

- Data: 2026-09-09
- Status: aceita
- Decisão: manter `FOUNDATION.md` como visão técnica cumulativa e documentos
  `PHASE_XX_*.md` como registros históricos das etapas e validações.
- Motivo: permitir que novas tarefas encontrem a arquitetura atual sem apagar o contexto
  factual verdadeiro no encerramento de cada fase.
- Consequências: mudanças factuais posteriores atualizam a documentação viva e recebem
  relatório próprio quando relevante; relatórios históricos não são reescritos.

## ADR-021 — Estados públicos e fases operacionais separadas

- Data: 2026-09-10
- Status: aceita
- Decisão: preservar `pending`, `running`, `succeeded`, `failed` e `cancelled`, mantendo a
  fase operacional em um campo separado.
- Motivo: conservar compatibilidade pública e ainda representar fila, carregamento,
  inferência, finalização e cancelamento.
- Consequências: consumidores usam `status` para o resultado estável e `phase` para o
  andamento detalhado.

## ADR-022 — Posse por lease e execução at least once

- Data: 2026-09-10
- Status: aceita
- Decisão: reivindicar jobs com transação SQLite, compare-and-set, identificador do worker
  e lease renovável; uma lease expirada pode reiniciar a tentativa desde o começo.
- Motivo: permitir recuperação determinística sem alegar retomada acústica ou garantia
  “exactly once” que o engine não oferece.
- Consequências: execução após crash é `at least once`; workers sem posse não atualizam nem
  publicam, e o limite de tentativas evita repetição indefinida.

## ADR-023 — Publicação idempotente e eventos persistentes

- Data: 2026-09-10
- Status: aceita
- Decisão: manter uma transcrição única por job, publicar resultado e sucesso na mesma
  transação e persistir eventos ordenados separadamente.
- Motivo: impedir resultados parciais e conservar progresso após reinicialização.
- Consequências: repetição da publicação concluída devolve o resultado existente; eventos
  de progresso não são checkpoints acústicos retomáveis.

## ADR-024 — Worker local sequencial e cancelamento cooperativo

- Data: 2026-09-10
- Status: aceita
- Decisão: usar concorrência padrão 1, sem timeout total, e verificar cancelamento entre
  segmentos e antes da publicação.
- Motivo: limitar memória e modelos simultâneos, aceitar gravações longas e respeitar o
  consumo lazy do Faster Whisper.
- Consequências: cancelamento pode aguardar carregamento do modelo ou outra operação
  indivisível; interrupções do processo são recuperadas pela lease.

## ADR-025 — API versionada e restrita ao loopback

- Data: 2026-09-10
- Status: aceita
- Decisão: expor contratos FastAPI sob `/api` e iniciar o servidor somente em
  `127.0.0.1`, validando `Host` e `Origin` local nas mutações.
- Motivo: permitir uso futuro pelo navegador sem transformar o produto em um serviço de
  rede pública nem revelar dados pessoais.
- Consequências: bind público é recusado, CORS wildcard não é habilitado e clientes locais
  usam a mesma origem ou uma origem HTTP de localhost aprovada.

## ADR-026 — Um consumidor por runtime no ciclo de vida HTTP

- Data: 2026-09-10
- Status: aceita
- Decisão: iniciar um worker sequencial no lifespan da aplicação e manter um lock de
  processo por runtime, recusando múltiplos consumidores Uvicorn.
- Motivo: evitar que uma configuração HTTP com vários processos duplique consumidores da
  fila SQLite e carregamentos de modelo.
- Consequências: `serve` exige um worker; o shutdown impede novas reivindicações e aguarda
  a operação corrente terminar antes de liberar o lock.

## ADR-027 — SSE reproduzido dos eventos SQLite

- Data: 2026-09-10
- Status: aceita
- Decisão: usar a sequência persistida por job como ID SSE, aceitar `Last-Event-ID`, enviar
  heartbeat e encerrar após o evento terminal.
- Motivo: recuperar eventos perdidos após reconexão sem manter progresso apenas em memória.
- Consequências: cada consulta abre e fecha sua conexão antes da espera; desconectar o
  navegador não cancela o job e a latência acompanha o intervalo conservador de consulta.

## ADR-028 — Mídia e exportações somente por identificadores

- Data: 2026-09-10
- Status: aceita
- Decisão: servir mídia e exportações gerenciadas por IDs, resolvendo internamente caminhos
  relativos já validados, com suporte a um Range de bytes para reprodução.
- Motivo: habilitar seek e downloads sem aceitar caminhos fornecidos pelo cliente.
- Consequências: ranges inválidos recebem 416, respostas omitem caminhos físicos e arquivos
  ausentes são tratados como inconsistência do runtime.

## ADR-029 — Interface vanilla empacotada com o servidor

- Data: 2026-09-10
- Status: aceita
- Decisão: servir HTML semântico, CSS e módulos JavaScript diretamente pelo FastAPI, na
  mesma origem da API, sem build obrigatório, framework de frontend ou CDN.
- Motivo: manter a instalação local simples, offline e compatível com o contrato de
  privacidade, sem introduzir um segundo runtime de produção.
- Consequências: assets entram como dados do pacote Python; a raiz entrega a aplicação e
  `/assets` serve somente arquivos controlados. Node pode ser usado para verificação de
  sintaxe no desenvolvimento, mas não é requisito de instalação nem execução.

## ADR-030 — DOM seguro, acessibilidade e fila recuperável no navegador

- Data: 2026-09-10
- Status: aceita
- Decisão: renderizar dados variáveis com `textContent` e criação explícita de elementos,
  usar controles HTML nativos e acompanhar jobs persistentes com `EventSource` após cada
  carga da interface.
- Motivo: impedir interpretação de dados do usuário como HTML, preservar navegação por
  teclado e recuperar progresso sem duplicar estado da fila no frontend.
- Consequências: não se usam sinks de HTML dinâmico; estados têm texto e regiões
  `aria-live`; desconexões SSE são anunciadas e reconectadas pelo navegador, enquanto o
  backend continua responsável por `Last-Event-ID` e replay dos eventos persistidos.

## ADR-031 — Pré-consulta de fila e retry SQLite limitado

- Data: 2026-09-10
- Status: aceita
- Decisão: consultar por trabalho reivindicável sem transação de escrita antes de entrar
  em `BEGIN IMMEDIATE`, revalidar integralmente dentro da transação e repetir somente
  falhas `SQLITE_BUSY` ou `SQLITE_LOCKED` com espera curta e limite consecutivo.
- Motivo: impedir que um worker ocioso cause starvation de uploads e outras mutações sem
  afrouxar a atomicidade da posse ou transformar todo acesso ao SQLite em lock global.
- Consequências: uma criação concorrente após pré-consulta vazia pode aguardar o próximo
  polling; dois workers ainda disputam por compare-and-set dentro da transação. Três
  retries transitórios são permitidos; erro permanente ou limite excedido é registrado,
  logado e encerra o controlador, sem loop infinito.
