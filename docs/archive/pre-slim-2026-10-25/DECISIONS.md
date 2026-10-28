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

## ADR-032 — Contextos assíncronos e cursores SSE monotônicos no navegador

- Data: 2026-09-11
- Status: aceita
- Decisão: associar cargas globais, pesquisas, leituras e exportações a gerações
  monotônicas, cancelar leituras HTTP substituídas quando possível e validar o contexto
  após cada espera. Associar ainda cada listener SSE a uma geração e a uma última sequência
  aceita por job, iniciando o stream no cursor informado pelo snapshot HTTP.
- Motivo: impedir que latência variável, reconexão ou callbacks tardios façam estado antigo
  substituir a seleção recente, repitam progresso já representado ou regressem um job.
- Consequências: respostas e falhas obsoletas são ignoradas; o download permanece ligado ao
  artefato solicitado, mas só a leitura ativa atualiza controles. O backend expõe
  `last_event_sequence` e aceita `after_sequence`, preservando `Last-Event-ID`, consultas
  parametrizadas, compatibilidade e schema v4.

## ADR-033 — Iniciador supervisionado somente para loopback

- Data: 2026-09-11
- Status: aceita
- Decisão: fornecer `scripts/start-local-transcriber.ps1` como atalho opcional para o
  entrypoint já instalado, em primeiro plano, fixando `127.0.0.1` e um worker, após checar
  `.venv` e a porta local.
- Motivo: reduzir erros de uso cotidiano sem esconder o processo, abrir bind público,
  instalar dependências ou iniciar downloads.
- Consequências: `Ctrl+C` permanece o caminho de encerramento supervisionado; uma porta
  ocupada produz orientação clara para escolher outra. O script não muda políticas globais
  do PowerShell, não move o runtime e não substitui a CLI.

## ADR-034 — Descoberta CUDA do Windows limitada ao processo

- Data: 2026-09-14
- Status: aceita
- Decisão: antes de importar CTranslate2, localizar somente diretórios padrão da NVIDIA
  compatíveis com CUDA 12 e cuDNN 9 e registrá-los com `os.add_dll_directory` no processo
  atual.
- Motivo: os instaladores gráficos podem não adicionar cuDNN ao `PATH`, enquanto a busca de
  DLLs do Python moderno é restrita. A GPU e o driver, isoladamente, não asseguram que
  CTranslate2 consiga carregar cuBLAS e cuDNN.
- Consequências: não se muda `PATH` global, não se copia DLL, não se aceita diretório
  fornecido pelo cliente e os handles são mantidos enquanto o processo existir. `cuda`
  continua sem fallback silencioso; `auto` mantém CPU `int8` quando a sondagem falha.

## ADR-036 — Instalação de usuário separada do desenvolvimento

- Data: 2026-10-13.
- Status: aceita no escopo de replicação autorizado por Erick.
- Decisão: caminho guiado Windows x64/Python 3.13 com venv próprio e instalação
  normal, sem `[dev]`, sem modelo/daemon implícito e sem alteração global.
  ZIP completo ou Git são equivalentes para obter o código; CPU é suficiente.
- Motivo: permitir instalação independente do computador/ambiente do autor.
- Consequências: smoke verifica wheel/assets/HTTP/SQLite em runtime sintético;
  workflow Windows preparado, sem alegar execução remota antes de publicação.
  Ranges permanecem no pyproject; não há lock bit a bit nem homologação de outros OS.
- Licenciamento: Erick escolheu uso pessoal e não comercial, registrado em LICENSE;
  dependências/modelos conservam suas próprias licenças. Não é licença irrestrita.

## ADR-035 — Exclusão preserva jobs ativos

- Data: 2026-09-14
- Status: aceita
- Decisão: rejeitar em transação imediata a exclusão de gravação que tenha job `pending`
  ou `running`, retornando conflito na API.
- Motivo: remover um job já reivindicado elimina o estado que o worker precisa consultar e
  pode encerrar o consumidor de fila por uma exceção não tratada.
- Consequências: o operador cancela ou aguarda o job antes da exclusão. Ausência excepcional
  de job reivindicado é tratada como perda de lease, permitindo que o worker continue;
  schema, eventos, retries SQLite limitados e contratos públicos permanecem compatíveis.

## ADR-037 — Opção opt-in de resumo estruturado via Sign in with ChatGPT

- Data: 2026-10-24
- Status: aceita
- Decisão: introduzir a interface abstrata LLMTransport desacoplando o transporte do
  Map-Reduce temporal do TranscriptSummarizer e adicionar ChatGPTTransport com suporte
  ao fluxo oficial de autenticação OAuth 2.0 PKCE / OIDC "Sign in with ChatGPT" para
  ferramentas open source (escopo chatgpt.tokens.use.direct, validação RS256/JWKS pura em
  Python sem dependências externas, rotação de refresh token salva em
  %LOCALAPPDATA%\LocalTranscriber\auth). O resumo com ChatGPT é estritamente opt-in pelo
  usuário, exigindo consentimento prévio e explícito antes de qualquer envio de texto da
  transcrição selecionada para a nuvem da OpenAI. Ollama local (qwen2.5:3b) permanece o
  motor padrão e 100% offline. A integração com ChatGPT consulta estritamente GET /v1/models
  para validar se o modelo gpt-6-luna está disponível no catálogo da conta conectada
  (rejeitando sem substituição caso indisponível) e realiza a inferência exclusivamente via
  POST /v1/responses com store: false, stream: true, model: "gpt-6-luna",
  reasoning: {"effort": "low"} e consumo completo de SSE até response.completed. Em caso
  de erro, quota excedida ou falha de rede/modelo, a execução falha explicitamente sem
  fallback automático para Ollama e sem persistir resumos parciais.
- Motivo: disponibilizar sumarizações avançadas utilizando o plano de assinatura ChatGPT
  existente do usuário via autorização oficial de compartilhamento de tokens para
  desenvolvedores open source, mantendo o controle, privacidade de dados e operação offline
  como padrões inalterados do produto.
- Consequências: a operação offline permanece garantida sem exigir login; tokens ficam
  isolados em diretório de runtime protegido fora do Git; nenhum token, dado pessoal,
  transcrição ou payload vaza para logs ou repositório; o formato estruturado
  TranscriptSummary (schema 1.0.0) e sidecars .resumo.md / .resumo.json permanecem
  inalterados, apenas registrando proveniência (provider="chatgpt", modelo). Testes
  automatizados operam 100% de forma sintética com mocks determinísticos sem chamadas à rede.

## ADR-038 — Conformidade estrita com a especificação oficial Sign in with ChatGPT (SIWC)

- Data: 2026-10-24
- Status: aceita
- Decisão: alinhar estritamente os contratos de autenticação, catálogo de modelos e streaming com a documentação oficial da OpenAI:
  1. Escopos completos: `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct` e inclusão mandatória de `resource: https://api.openai.com/v1` em autorização, troca de código e renovação de tokens.
  2. Registro dinâmico de cliente e reautorização: na primeira inscrição, o `client_id` emitido pelo IdP é preservado em arquivo protegido `client_id.txt`; em reautorizações subsequentes, o `client_id` original é preservado (trocas inesperadas são rejeitadas), `agent_name_hint` é omitido e `id_token_hint` da conta salva é enviado.
  3. Validação rigorosa pré-armazenamento: ID token RS256/JWKS obrigatório e checagem de escopos concedidos antes de gravar credenciais em disco.
  4. Proteção de armazenamento Windows NTFS: assegurar acesso restrito ao usuário via ACL nativa (`icacls /inheritance:r /grant:r %USERNAME%:(R,W)`), falhando fechado se a restrição não puder ser aplicada; evitar alegar segurança por chmod POSIX em ambiente Windows.
  5. Restrição de callback loopback a `127.0.0.1`: proibir `localhost` (incompatível com o IdP oficial) e domínios externos; validar `state` obrigatoriamente inclusive em retornos de erro do IdP com TTL de 10 min; aplicar escape HTML estrito em mensagens de erro e emails para mitigar vulnerabilidades de XSS e injeção de tags.
  6. Catálogo oficial `/v1/models` e status: inspecionar o array `models` contendo objetos com `slug` e `visibility`, exigindo `gpt-6-luna`; endpoint de status informa `has_luna=False` em qualquer falha de consulta ou expiração de token.
  7. Streaming SSE e desduplicação de texto: consumir eventos oficiais `response.output_text.delta` (com suporte retrocompatível a `response.text.delta`) e ignorar conteúdo textual repetido nos eventos posteriores `response.output_item.done` e `response.completed` quando deltas incrementais já foram acumulados.
- Motivo: garantir interoperabilidade robusta e segura com o fluxo oficial de autorização e inferência da OpenAI sem incorrer em falhas de callback, duplicações de streaming, vazamentos de autorização ou fragilidades de controle de acesso no sistema de arquivos.
- Consequências: conformidade estrita com o contrato oficial; resiliência aprimorada contra interrupções de streaming e ataques locais de injeção; ausência de regressão na operação offline existente.

## ADR-039 — Gateway privado FastAPI em loopback para ingestão remota restrita (Etapa 8J-A)

- Data: 2026-10-24
- Status: aceita
- Decisão: introduzir o módulo `remote_gateway.py` como uma aplicação FastAPI independente, desligada por padrão (arquivo de configuração `remote/gateway.json`) e vinculada exclusivamente ao loopback (`127.0.0.1`), projetada para atuar como fronteira de ingestão para clientes autorizados (ex.: iPad via Tailscale):
  1. Isolamento arquitetural: processo e porta separados da core API (porta padrão `8766` vs `8765`, configurável via CLI, sempre em `127.0.0.1`), sem reutilização de rotas core, sem CORS e sem exposição de endpoints administrativos ou do sintetizador LLM (Ollama/ChatGPT). A core API permanece 100% restrita ao loopback local.
  2. Identidade Tailscale confiável: autenticação baseada no cabeçalho de identidade injetado pelo proxy local confiável (`Tailscale-User-Login`), exigindo correspondência exata contra allowlist estática (`allowed_identities`); cabeçalho ausente ou vazio resulta em 401, duplicado ou não autorizado resulta em 403; requisições contendo `Tailscale-Funnel-Request` são rejeitadas com 403. O gateway opera em `proxy_headers=False` no Uvicorn e rejeita qualquer binding em interfaces públicas.
  3. Proteção contra CSRF e validação de origem: prefixo de rotas `/remote/v1`; validação estrita de `Host` (hostname bare em allowlist, rejeitando porta, path, query, fragment ou userinfo) e `Origin` HTTPS exato (sem barra final ou porta inesperada); sessão com cookie contendo identificador de sessão aleatório (`SameSite=Strict`, `HttpOnly`, `Secure` no caminho `/remote/v1`) e token CSRF assinado por HMAC-SHA256 vinculado à sessão e à identidade, derivado de segredo `remote/csrf.key` protegido com ACL restrita do Windows (`icacls`), validada e reaplicada no startup.
  4. Mitigação de IDOR: registros de áudio e jobs enfileirados são vinculados à chave HMAC da identidade no banco de estado próprio (`remote/gateway.sqlite3`), impedindo que um usuário acesse áudios ou transcrições de outro usuário ou importados localmente. Um `recording_id` em estado `completed` não pode ser associado a identidades distintas.
  5. Proteção de I/O, streaming e sanitização: exigência obrigatória de cabeçalho `Content-Length` (411 se ausente ou chunked), contagem de bytes em streaming abortando se exceder o limite (`max_upload_bytes`), timeout total da recepção do corpo (`request_timeout_seconds`, padrão 600s), checagem antecipada de disco livre com lock de upload serializando requisições no processo gateway contra concorrência TOCTOU (concorrência com importações locais no core não medida em hardware real), limpeza de arquivos parciais órfãos e sanitização de duplicatas (`DuplicateMediaError` ou colisões de integridade SHA-256 retornam 409 sanitizado sem expor o ID existente).
  6. Idempotência transacional e falha fechada: suporte a `Idempotency-Key` no upload e na criação de jobs; `claim_upload` em estado `importing` recente retorna 409 busy; após crash ou expiração de claim em `importing`, caso a mídia já exista no core, a requisição falha fechada com 409 sanitizado para impedir IDOR entre identidades distintas (dada a impossibilidade de provar posse retrospectiva sem alteração estrutural no schema v4 do core). Exclusão de gravação no core resulta em 410 no agendamento de jobs, liberando a claim transacionalmente.
- Motivo: permitir envio de áudios e leitura de transcrições a partir de dispositivos remotos de confiança sem violar as garantias de privacidade, sem expor rotas do sistema local e sem adicionar um segundo worker concorrente.
- Consequências: operação validada por testes sintéticos determinísticos (83 testes dedicados do gateway e 63 regressões do core); o acesso em rede real depende do correto provisionamento de proxy autenticado do usuário (ex.: Tailscale), o qual permanece desativado nesta etapa; testes com mocks determinísticos não constituem prova de segurança de rede Tailscale em produção.

## ADR-040 — Sessão privada temporária, controle seletivo Tailscale Serve e verificação fail-closed de processo (Etapa 8J-1)

- Data: 2026-10-25
- Status: aceita
- Decisão: implementar o gerenciador de ciclo de vida de sessão temporária no módulo `remote_session.py` e comandos `local-transcriber remote-session start/status/stop`:
  1. **Plano de Controle Estritamente Local**: a inicialização e o encerramento da sessão ocorrem apenas sob demanda explícita do usuário no notebook via CLI ou launcher PowerShell. Nenhuma rota de controle é exposta pelo gateway remoto.
  2. **Tailscale Serve com Escopo Restrito**: o proxy reverso é configurado exclusivamente para a porta e URL do gateway (`tailscale serve --bg --https=443 http://127.0.0.1:8766`). O Tailscale Funnel é expressamente proibido e bloqueado. Ao encerrar a sessão, executa-se apenas a desativação seletiva da porta (`tailscale serve --https=443 off`). É terminantemente proibido o uso de `tailscale serve reset` (que destruiria configurações alheias do operador) ou `tailscale down`.
  3. **Verificação de Propriedade de Processo (`ProcessVerifier`)**: o encerramento do processo do gateway valida mandatoriamente o timestamp de criação (`GetProcessTimes` no Windows) e os argumentos da linha de comando (`--session-id=<uuid>`). Se houver divergência (indicando reciclagem de PID pelo sistema operacional) ou o processo não pertencer à aplicação, a operação falha de forma fechada com `RemoteSessionOwnershipError`, recusando-se a finalizar o processo.
  4. **Preservação do Core API e Jobs**: a sessão remota conecta-se apenas ao gateway (`8766`). O Core API (`8765`), o worker sequencial único e todos os jobs da fila SQLite são mantidos em execução normal e inalterados durante e após o ciclo da sessão remota.
  5. **Rollback Transacional**: falhas no startup do Tailscale Serve revertem o processo do gateway e limpam o arquivo efêmero `session.json`.
- Motivo: proporcionar uma experiência operacional previsível e segura para o usuário acessar o Local Transcriber de seu iPad na tailnet privada, prevenindo sequestro de processos, vazamento de portas globais ou interrupção acidental de jobs de transcrição locais.
- Consequências: gerenciamento autônomo e temporário testado deterministamente com mocks sintéticos (19 testes em `tests/test_remote_session.py`); garantia de fail-closed e integridade de dados; validação física ponta a ponta programada para o gate 8J-B.

## ADR-041 — Hardening pré-gate da sessão temporária remota e mitigação de vulnerabilidades (Etapa 8J-0)

- Data: 2026-10-25
- Status: aceita
- Decisão: complementar e blindar a arquitetura de sessão temporária remota antes do fechamento do Gate 1 e do início da Etapa 2:
  1. **Posse de Processo Estritamente Fail-Closed**: `ProcessVerifier` declara tipos formais do Win32 (`wintypes.HANDLE`, `wintypes.BOOL`, `wintypes.DWORD`, `wintypes.LPFILETIME`) eliminando riscos de truncamento de ponteiros de 64 bits em inteiros de 32 bits no Windows. Recusa metadados nulos (`expected_creation_time` ou `expected_marker` nulos falham fechado imediatamente) e valida argumentos via tokenização `shlex` exata, impedindo falsos positivos por mera substring.
  2. **Inspeção Prévia Rigorosa de Serve e Bloqueio de Funnel**: `TailscaleCli.serve_status` opera com falha fechada para códigos de saída não-zero ou JSON inválido. A inicialização da sessão rejeita incondicionalmente Tailscale Funnel ativo/configurado e aborta se a porta HTTPS já estiver associada a qualquer rota externa.
  3. **Desligamento Seletivo Condicionado a Prova de Mapping**: o comando `stop` só executa `tailscale serve --https=443 off` caso a consulta a `serve_status` comprove que a porta pertence estritamente ao backend da sessão local (`http://127.0.0.1:8766`). Se a rota apontar para serviço de terceiro ou estiver em estado desconhecido, o mapping externo é preservado.
  4. **Status Estritamente Observacional**: `RemoteSessionManager.status` opera em modo somente leitura, nunca emitindo comandos de rede nem destruindo arquivos de sessão caso o PID não esteja ativo.
  5. **Transacionalidade e Retenção de Metadados de Recuperação em `stop`**: a terminação do PID do gateway é verificada; caso o processo persista, o arquivo `session.json` é preservado para diagnóstico e auditoria, levantando `RemoteSessionError`.
  6. **Serialização Concorrente**: implementado o context manager `_session_lock` (`.session.lock`) para prevenir colisões simultâneas de `start` e `stop`.
  7. **Validação de Limites e Timeouts**: portas numéricas validadas estritamente na faixa 1-65535 e timeout fixado em 15 segundos em todas as chamadas do Tailscale.
  8. **Readiness Probe Autenticado**: endpoint `GET /remote/v1/health` disponibilizado sob loopback e protegido pelo middleware de autenticação (exige `Host` e `Tailscale-User-Login`), expondo unicamente `{"status": "ok"}` sem vazamento de estado interno.
  9. **Entrypoint Modular do CLI**: adicionada cláusula canônica `if __name__ == '__main__': sys.exit(main())` no `cli.py`, permitindo execução correta de subprocessos filhos com `python -m local_transcriber.cli`.
- Motivo: fechar vulnerabilidades de confiabilidade levantadas na Seção 3 de `REMOTE_ACCESS_NEXT_IMPLEMENTATIONS.md` e atender integralmente aos critérios do Gate 1.
- Consequências: resiliência aprimorada, 36 testes específicos de sessão remota e 319 testes na suíte completa aprovados com 100% de sucesso determinístico sem efeitos colaterais.


## ADR-042 — Journal recuperável e posse integral de Serve (complemento da Etapa 1)

- Data: 2026-10-25.
- Status: implementação local para revisão do coordenador; não representa aprovação do gate.
- Decisão: complementar ADR-040/041 com journal antes de efeitos (`prepared`, `gateway`,
  `activating`, `active`), gravação temporária com flush/fsync e replace e rollback seletivo.
  Falhas de consulta, off, confirmação posterior, persistência ou rollback conservam
  recuperação. Stale usa o mesmo protocolo. Journal corrompido/incompleto não é ausência.
- Posse de Serve: aceitar off somente quando TCP HTTPS, host DNS, única rota raiz e
  único Proxy exato pertencerem à sessão inteira. Estruturas desconhecidas, serviços e
  handlers adicionais bloqueiam mutações. Outras portas permanecem intocadas.
- Consequências: estados sem PID comprovado exigem reconciliação manual; falhas de rede
  podem manter gateway e mapping ativos para recuperação explícita. A trava da aplicação
  não serializa clientes Tailscale externos nem garante durabilidade contra queda de energia.
- Evidência: 101 testes de sessão, 194 focados e 384 na suíte completa; ctypes com HANDLE
  alto e trava concorrente possuem testes próprios. A declaração anterior de cobertura
  não substitui esses testes. [Relatório posterior](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md).
- Próximo gate: revisão independente, seguida de nova autorização para qualquer Etapa 2.

## Ferramentas do agente (2026-10-25)

Usar o servidor oficial remoto do GitHub por uma ponte stdio com vers?o fixada, reutilizando o armazenamento de credenciais do GitHub CLI. O token existe somente em mem?ria/ambiente do processo; n?o ? inclu?do em configura??o, argumentos ou documenta??o. Restringir filesystem ? raiz do checkout e instalar Impeccable no escopo do projeto. Consequ?ncias: depend?ncia de Node.js/npx, GitHub CLI autenticado e conectividade para o MCP GitHub; nenhuma depend?ncia nova no runtime do aplicativo.


## Integra??o MCP Graphify (2026-10-25)

Consultar o grafo local preferencialmente pelo MCP Graphify, mantendo skill/CLI como alternativa. Para opera??es no GitHub, priorizar o MCP GitHub; usar CLI quando a opera??o n?o existir no MCP ou o servidor estiver indispon?vel. Configura??o de ferramentas n?o autoriza a??es de publica??o.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.


## Ferramentas Serena MCP e leitura cirúrgica (2026-10-25)

Serena é provisionado via pipx isolado, com backend LSP/Pyright, contexto
`ide-assistant` e interface `tools` explícita para expor as operações simbólicas
individuais. A configuração local desativa o dashboard. `.serena/project.yml`
restringe servidores de linguagem a Python e ignora artefatos/ambientes; o
`.gitignore` dessa pasta exclui cache e memórias gerados, preservando a configuração.
Graphify orienta a busca de relações; Serena lê símbolos atuais delimitados.
GitHub usa exclusivamente o MCP separado do projeto, com fallback CLI quando
necessário; o conector interno é proibido. Revisão de release exige pedido
explícito e não decorre de solicitação direta de commit/push.
