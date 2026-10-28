# Limitações e problemas conhecidos

Estes itens registram limites atuais do produto. Um problema conhecido não é, por si
só, uma tarefa autorizada; qualquer mudança continua dependente do escopo solicitado.

## Codecs disponíveis

- Descrição: os codecs concretamente disponíveis dependem do FFmpeg incorporado ao PyAV.
- Impacto: uma mídia pode não ser decodificável na distribuição instalada.
- Situação atual: a importação rejeita conteúdo que não consegue validar e decodificar.
- Possível direção futura: validar a matriz real de formatos e codecs suportados.
- Fase provável: validação futura autorizada.

## Duplicidade somente por bytes

- Descrição: SHA-256 reconhece igualdade exata dos bytes, não equivalência perceptual.
- Impacto: duas codificações do mesmo áudio são tratadas como arquivos diferentes.
- Situação atual: comportamento deliberado e determinístico.
- Possível direção futura: avaliar identificação perceptual apenas se houver escopo próprio.
- Fase provável: não definida no roadmap atual.

## Sem conversão ou normalização

- Descrição: a biblioteca não converte, normaliza nem edita mídia.
- Impacto: o arquivo é preservado no formato importado e precisa ser aceito pelo PyAV.
- Situação atual: fora das funcionalidades implementadas.
- Possível direção futura: definir processamento de mídia em uma fase específica.
- Fase provável: não definida no roadmap atual.

## Janela entre filesystem e SQLite

- Descrição: uma interrupção abrupta pode ocorrer entre a operação no arquivo e a transação SQLite.
- Impacto: pode restar inconsistência que os fluxos normais de compensação não alcançam.
- Situação atual: exceções normais limpam ou restauram arquivos; queda abrupta não tem recuperação automática.
- Possível direção futura: adicionar reconciliação explícita do runtime.
- Fase provável: não definida no roadmap atual.

## Pesquisa básica

- Descrição: a pesquisa FTS5 não oferece ranking nem filtros avançados além do limite.
- Impacto: resultados não têm ordenação por relevância nem refinamentos adicionais.
- Situação atual: pesquisa textual local e parametrizada está disponível.
- Possível direção futura: desenhar ranking e filtros conforme necessidades confirmadas.
- Fase provável: não definida no roadmap atual.

## Reexportação exige gestão explícita

- Descrição: reexportar o mesmo formato para a mesma transcrição exige gerir o artefato existente.
- Impacto: a operação não substitui implicitamente uma exportação anterior.
- Situação atual: comportamento explícito existente desde a versão 0.2.0.
- Possível direção futura: definir política segura de substituição ou versionamento.
- Fase provável: não definida no roadmap atual.

## Caracterização real ainda parcial

- Descrição: três validações reais confirmaram o modelo `small` em CPU `int8`, mas usaram
  apenas gravações curtas em português e não possuíam gabarito textual independente.
- Impacto: o fluxo real está comprovado, porém qualidade, precisão, desempenho em cargas
  maiores e variedade de mídia ainda não foram caracterizados.
- Situação atual: a Etapa 7 verificou upload, job HTTP, worker, SSE, busca, leitura, Range,
  segmentos, palavras, métricas, cinco exportações e persistência. Os RTFs observados foram
  1,612, 0,4778 e aproximadamente 0,816; essa variação e amostras curtas não caracterizam
  cargas longas. Nenhuma taxa de precisão foi calculada.
- Possível direção futura: executar uma matriz sanitizada de formatos, durações e gabaritos.
- Fase provável: validação futura autorizada.

## Vocabulário técnico específico

- Descrição: a segunda validação real apresentou erros em vocabulário técnico específico.
- Impacto: termos especializados podem ser transcritos incorretamente mesmo quando o
  fluxo, os números principais e a estrutura temporal estão corretos.
- Situação atual: a limitação foi observada sem gabarito textual independente e não indica
  falha de implementação no fluxo da Etapa 3.
- Possível direção futura: qualquer adaptação contextual deve ter escopo próprio e ser
  avaliada contra gabarito independente, sem inferir precisão a partir das amostras atuais.
- Fase provável: não definida no roadmap atual.

## Caracterização CUDA ainda parcial

- Descrição: CUDA 12, cuBLAS 12 e cuDNN 9 foram carregados localmente e a 7B confirmou
  `small` com `int8_float16` em uma amostra curta.
- Impacto: a aceleração está operacional, mas desempenho, estabilidade térmica, consumo de
  VRAM, qualidade textual, modelos maiores, duração longa e diversidade de codecs não
  podem ser inferidos dessa amostra.
- Situação atual: a aplicação registra somente no processo atual os diretórios padrão da
  NVIDIA, sem mudar `PATH` global. A comparação controlada não produziu segmentos ou
  palavras; o operador relatou testes posteriores de áudio em CUDA, sem métricas ou
  conteúdo registrados pela entrega.
- Possível direção futura: executar matriz sanitizada e autorizada de modelos, durações,
  codecs, temperatura e gabaritos independentes, sem download automático de modelo.
- Fase provável: validação futura autorizada.

## Recuperação reinicia a inferência

- Descrição: o Faster Whisper atual não retoma do ponto acústico após perda da lease.
- Impacto: um job recuperado pode repetir o processamento completo e consumir tempo extra.
- Situação atual: a execução é `at least once`, com limite de tentativas; publicação final
  é idempotente e continua limitada a uma transcrição por job.
- Possível direção futura: avaliar checkpoints apenas se o engine oferecer suporte seguro.
- Fase provável: não definida no roadmap atual.

## Breve sobreposição de computação após expiração

- Descrição: a perda ou expiração da lease é percebida em pontos cooperativos; uma
  operação indivisível do engine pode continuar por um curto intervalo até o próximo.
- Impacto: depois que outro worker recupera o job, as duas inferências podem se sobrepor
  temporariamente em computação, embora somente uma lease seja válida.
- Situação atual: somente o proprietário atual pode persistir progresso, cancelar, marcar
  falha ou publicar. O worker obsoleto abandona a tentativa ao observar o sinal ou a
  validação transacional; nunca há duas publicações finais para o mesmo job.
- Possível direção futura: medir a latência até os pontos cooperativos com inferência real.
- Fase provável: validação futura autorizada.

## Cancelamento não instantâneo

- Descrição: o cancelamento é verificado cooperativamente durante o consumo de segmentos.
- Impacto: carregamento do modelo e operações indivisíveis podem atrasar a parada.
- Situação atual: a solicitação é persistida imediatamente e impede publicação posterior;
  jobs pendentes são cancelados sem iniciar inferência.
- Possível direção futura: medir latência e pontos de cooperação com inferência real.
- Fase provável: validação futura autorizada.

## Recuperação operacional real ainda parcial

- Descrição: a fila concluiu job real pelo worker integrado e recuperou um job após reinício
  do computador, mas lease expirada, cancelamento e retry não foram executados de modo
  controlado com inferência real nesta amostra curta.
- Impacto: custos e latências desses cenários sob Faster Whisper real ainda não foram
  caracterizados.
- Situação atual: áudio simulado de duas horas prova ausência de timeout artificial, e os
  cenários de lease, cancelamento e retry usam engines falsos determinísticos. A Etapa 7
  observou recuperação real após reinício, mas evitou duplicar a inferência e a transcrição
  da amostra apenas para provocar esses estados.
- Possível direção futura: executar cenários sanitizados de carga e interrupção reais com
  consentimento operacional específico.
- Fase provável: validação futura autorizada.

## Visualizador OpenAPI offline ausente

- Descrição: Swagger UI e ReDoc não são expostos; somente `/api/openapi.json` está
  disponível.
- Impacto: não há navegação visual dos contratos no navegador nesta versão.
- Situação atual: remover o Swagger padrão elimina referências a CDN e mantém o CSP e a
  operação offline coerentes.
- Possível direção futura: incorporar um visualizador totalmente local apenas em etapa
  explicitamente autorizada, sem baixar assets durante a execução.
- Fase provável: não definida no roadmap atual.

## Reprodução depende dos codecs do navegador

- Descrição: a biblioteca aceita os contêineres e codecs decodificáveis pelo PyAV, mas o
  player HTML usa os codecs oferecidos pelo navegador instalado.
- Impacto: uma gravação válida para transcrição pode não ser reproduzível diretamente no
  navegador, embora continue disponível para processamento e exportação.
- Situação atual: o endpoint de mídia suportou Range na validação real e o player local
  carregou controles e marcadores temporais, sem expor caminhos físicos; a aplicação não
  converte nem normaliza a mídia.
- Possível direção futura: validar uma matriz sanitizada de codecs no ambiente-alvo e
  avaliar conversão somente em escopo próprio.
- Fase provável: validação futura autorizada.

## Seleção de leitura não persiste após recarga

- Descrição: a gravação aberta na tela de leitura é um estado de navegação do navegador e
  não é persistida no SQLite nem codificada na URL.
- Impacto: após recarregar a página, é necessário abrir novamente a gravação pela
  biblioteca; jobs e progresso continuam recuperados da fila persistente.
- Situação atual: decisão conservadora da primeira interface, sem criar novo estado de
  domínio ou alterar o schema v4.
- Possível direção futura: avaliar URLs locais endereçáveis e restauração de navegação.
- Fase provável: não definida no roadmap atual.

## Encerramento aguarda a operação corrente do engine

- Descrição: o shutdown impede novas reivindicações, mas não interrompe à força uma chamada
  indivisível do engine já em andamento.
- Impacto: encerrar o servidor durante carregamento ou inferência pode aguardar o ponto em
  que o job termina ou observa seu cancelamento cooperativo.
- Situação atual: a política evita abandonar uma thread de inferência ou cancelar um job
  apenas porque o servidor recebeu shutdown.
- Possível direção futura: medir a latência real e avaliar pontos adicionais de cooperação.
- Fase provável: validação futura autorizada.

## SSE usa consulta periódica conservadora

- Descrição: depois de drenar incrementalmente todos os eventos posteriores ao cursor,
  novos eventos são detectados por consultas SQLite curtas em intervalo fixo; não há
  notificação cross-thread nativa no SQLite.
- Impacto: existe pequena latência entre persistência e entrega do evento.
- Situação atual: as consultas filtram job e sequência, usam lote limitado e não relêem o
  histórico; nenhuma transação permanece aberta durante a espera e heartbeat mantém a
  conexão observável sem polling agressivo. O navegador inicia no cursor do snapshot,
  acompanha cada job separadamente e rejeita eventos duplicados, regressivos, fora de ordem
  ou oriundos de listeners encerrados. A Etapa 7 também confirmou replay do evento terminal
  persistido a partir de `Last-Event-ID`.
- Possível direção futura: ajustar o intervalo após medições reais, preservando replay.
- Fase provável: validação futura autorizada.

## Disponibilidade de Ollama e modelo local

- Descrição: a sumarização estruturada pedagógica depende da disponibilidade do serviço local
  Ollama em `http://127.0.0.1:11434` e do modelo `qwen2.5:3b` previamente baixado pelo operador.
- Impacto: se o daemon do Ollama estiver inativo, não responder ou o modelo não estiver instalado,
  a solicitação de resumo não é concluída.
- Situação atual: a falha é tratada com resposta HTTP 503 sanitizada e segura, sem qualquer
  fallback para serviços externos ou vazamento de dados.
- Possível direção futura: adicionar verificação de saúde e presença de modelo nas rotas de
  capacidade da API e na interface web.
- Fase provável: melhoria futura autorizada.

## Limites remanescentes da manutenção 8C

- Dívida Ruff E501/formatação resolvida: check global e format --check aprovados
  em src/tests. A 8C mudou somente estilo de quatro arquivos e os testes da fila.
- O teste de retries usa relógio controlado; expiração/margem de lease tem
  regressão separada. Isso remove a competição entre duas condições de parada.
  A causa exata do evento histórico 8B permanece desconhecida. Timeouts externos
  de sincronização permanecem limites sob sobrecarga extrema.
- Aviso pip histórico da 8C resolvido na manutenção 8E por quarentena reversível
  dos dois metadados antigos; pip check atual retorna 0 sem aviso.
- Não há validação nova de inferência, CUDA, daemon Ollama ou mídia real.
- Artefatos sintéticos remanescentes da limpeza 8B foram preservados; inventário
  anterior completo desconhecido. A 8C usou checkout e temporários novos isolados,
  sem apagar diretórios de fixtures.

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

## Disponibilidade de modelos no plano ChatGPT do usuário

- Descrição: o acesso ao modelo `gpt-6-luna` depende dos modelos disponibilizados pela OpenAI
  para a conta do usuário no endpoint `/v1/models`.
- Impacto: caso o modelo `gpt-6-luna` não esteja listado no catálogo retornado com o token
  OAuth do usuário, a síntese via ChatGPT é recusada com `ChatGPTModelUnavailableError`.
- Situação atual: comportamento estrito e deliberado; a aplicação não substitui silenciosamente
  o modelo por outro nem realiza fallback não autorizado para o Ollama.
- Possível direção futura: permitir seleção explícita entre modelos suportados presentes na conta
  caso a OpenAI amplie os modelos autorizados para token-sharing.
- Fase provável: evolução futura sob escopo próprio.

## Limitações de preview da API Responses com compartilhamento de tokens

- Descrição: a rota `/v1/responses` via `chatgpt.tokens.use.direct` opera sob regras de preview
  documentadas oficialmente pela OpenAI (exigência estrita de `store: false` e `stream: true`).
  Além disso, campos como `text.format` estruturado não são uniformemente suportados no canal
  de planos em preview.
- Impacto: a conformidade com o esquema JSON `TranscriptSummary` (schema 1.0.0) é garantida por
  regras estritas no prompt do sistema e pelo validador/extrator local `_extract_json`, falhando
  com `ChatGPTInferenceError` caso o modelo retorne JSON truncado ou inválido.
- Situação atual: comportamento adaptado e validado deterministicamente por testes unitários e de integração.
- Possível direção futura: adotar schema enforcement nativo assim que formalmente estabilizado pela OpenAI.
- Fase provável: evolução futura sob escopo próprio.


## Gateway remoto restrito a testes sintéticos / ausência de validação em rede Tailscale real

- Descrição: a implementação da Etapa 8J-A do gateway privado (`remote_gateway.py`) foi validada
  exclusivamente por meio de 83 testes sintéticos com mocks determinísticos em loopback local
  (`127.0.0.1`). Não foi ativado proxy Tailscale Serve ou Funnel, nem foi estabelecida conexão real
  com dispositivo cliente (iPad) ou tráfego em rede privada externa.
- Impacto: testes sintéticos com cabeçalhos simulados não constituem prova de segurança contra
  falsificação em ambiente de rede com proxies desconfigurados. A segurança efetiva depende de o
  operador configurar um proxy que garanta a sanitização do cabeçalho `Tailscale-User-Login`
  antes de encaminhar requisições ao loopback do notebook.
- Situação atual: comportamento seguro por padrão (gateway desligado, bind restrito a 127.0.0.1,
  `proxy_headers=False` no Uvicorn). O software não abre nem expõe portas externas.
- Possível direção futura: portão de validação física com Tailscale real em dispositivo controlado
  antes de autorizar uso regular.
- Fase provável: Etapa 8J-B / validação física.

## Ausência de interface web no gateway remoto (Etapa 8J-A)

- Descrição: o gateway privado expõe exclusivamente endpoints REST de sessão, upload e jobs sob o prefixo `/remote/v1`
  (`GET /remote/v1/session`, `POST /remote/v1/uploads`, `POST /remote/v1/jobs`, `GET /remote/v1/jobs/{id}`,
  `GET /remote/v1/jobs/{id}/transcript`), sem servir a interface web vanilla do Local Transcriber.
- Impacto: o acesso remoto pelo iPad deve ocorrer via atalhos do iOS, scripts de automação ou cliente
  HTTP compatível; a interface visual principal continua acessível apenas localmente na porta 8765.
- Situação atual: estritamente conforme o escopo da Etapa 8J-A (ingestão e leitura sem UI).
- Possível direção futura: disponibilização opcional de página web mínima para dispositivos móveis
  em etapas futuras caso demandado.
- Fase provável: evolução futura sob escopo próprio.

## Idempotência de recuperação pós-crash do gateway restrita pela imutabilidade do schema core v4 (Etapa 8J-A)

- Descrição: caso ocorra um crash fatal do processo exatamente após o commit da importação de mídia no banco core (`recordings`) e antes da atualização de estado no banco do gateway (`remote/gateway.sqlite3`), uma tentativa subsequente de retry com a mesma `Idempotency-Key` falhará fechada com código 409 ("this media already exists in the notebook library") em vez de retornar 200 com a gravação associada.
- Impacto: a tabela `recordings` do schema SQLite v4 central não possui campos de metadados para armazenar chaves de gateway ou hashes de identidade. Logo, ao detectar a presença do SHA-256 na biblioteca central após um crash, o sistema não pode comprovar sem ambiguidade se aquela mídia foi importada pelo autor da requisição ou por outra identidade/operação local concorrente. Para erradicar qualquer vulnerabilidade de IDOR, o gateway recusa vincular a posse retrospectivamente e falha fechado com 409 sanitizado.
- Situação atual: comportamento seguro por padrão (fail-closed contra IDOR), amplamente testado de forma determinística na suíte de testes.
- Possível direção futura: eventual inclusão de coluna de proveniência de gateway em futura migração planejada de schema (v5).
- Fase provável: evolução de schema em fase futura dedicada.

## Validação de sessão remota e Tailscale Serve restrita a mocks sintéticos (Etapa 8J-1 e Etapa 0)

- Descrição: o complemento posterior possui 101 testes de sessão, com runners/inspetores sintéticos, callbacks ctypes para HANDLE de 64 bits e trava real do SO em concorrência start/start, start/stop, stop/start e stop/stop. São 194 testes focados e 384 na suíte completa aprovados. Não foi executado `tailscale.exe` nem ativado tráfego real na tailnet durante esta entrega.
- Impacto: em ambientes reais, a correta descoberta de nós e término TLS dependem de o operador possuir o Tailscale instalado e conectado à sua conta com MagicDNS ativo.
- Situação atual: falhas de consulta/off e limpeza stale preservam o journal; persistência antecede spawn e ativação; estruturas Serve desconhecidas ou com terceiros bloqueiam mutações. O relatório histórico de hardening declarou cobertura de concorrência/ctypes sem testes específicos suficientes; a evidência posterior está no [complemento](PHASE_08J_STAGE1_RECOVERY_COMPLEMENT_2026-10-25.md). Gate ainda pendente de revisão independente.
- Possível direção futura: validação física ponta a ponta na Etapa 8J-B / Etapa 5.
- Fase provável: Etapa 8J-B / Etapa 5 (validação física).

## Recuperação conservadora do journal remoto e concorrência externa

- Um crash entre spawn e persistência de PID pode deixar `prepared` sem prova completa
  de processo. O marcador permanece no journal, mas `start/stop` bloqueiam e exigem
  reconciliação manual local. Estado corrompido ou temporário sem journal também é
  preservado; não apagar arquivos para contornar o bloqueio sem verificar processo/rede.
- Configurações Serve desconhecidas, serviços, múltiplos hosts/rotas, handlers estáticos
  ou forwarding TCP na porta escolhida são recusados. É uma restrição conservadora;
  não há tentativa de normalizar ou apagar configuração de terceiros.
- A trava serializa somente esta aplicação. O CLI Tailscale não oferece aqui uma
  transação/CAS contra alterações externas entre inspeção e comando. Não editar Serve
  simultaneamente por outros clientes. Queda de energia e recuperação física não foram
  homologadas; fsync/replace e falhas de processo foram exercitados sinteticamente.
- Próxima ação: revisão independente do complemento. Etapas posteriores exigem nova
  autorização explícita; esta entrega não homologa operação móvel real.

## Matéria fixa no arquivo de configuração do gateway na Etapa 1 da Fase 8J

- Descrição: na Etapa 1, todos os uploads recebidos pelo gateway são associados ao `subject_id` estático definido em `%LOCALAPPDATA%\LocalTranscriber\remote\gateway.json`.
- Impacto: o cliente móvel não pode selecionar dinamicamente a matéria de destino no momento do envio.
- Situação atual: comportamento planejado para a Etapa 1 conforme `docs/REMOTE_ACCESS_INTEGRATION_PLAN.md`.
- Possível direção futura: implementação da Etapa 2 com allowlist de matérias autorizadas e rota `GET /remote/v1/subjects`.
- Fase provável: Fase 8J — Etapa 2.


## Ferramentas do agente (2026-10-25)

A descoberta dos novos MCPs pela sess?o do agente requer reabrir a sess?o. O MCP GitHub depende de autentica??o v?lida no GitHub CLI, Node.js, npx e rede; filesystem depende de Node.js/npx. Impeccable foi instalada como skill, sem instalar ou aprovar hooks. O checkout mant?m altera??es anteriores n?o commitadas; igualdade de HEAD com o remoto n?o significa igualdade integral dos arquivos.


## Integra??o MCP Graphify (2026-10-25)

O MCP Graphify funciona com o grafo salvo, mas graph_stats alerta que seu commit de constru??o difere do HEAD atual. Rela??es e localiza??es devem ser conferidas no c?digo atual. Reabrir a sess?o para carregar o novo servidor; descoberta nesta sess?o ainda n?o comprovada. A consulta de valida??o foi limitada a 500 tokens e truncada; comprovou transporte e recupera??o, n?o cobertura integral.


## Inicializa??o do MCP Git (2026-10-25)

O lan?ador `pipx run` excedeu 55 segundos sem responder ao initialize; o log parou antes do servidor, com bloqueio de cache existente. A configura??o local passou a invocar diretamente o execut?vel j? dispon?vel no cache pipx, com diret?rio de trabalho fixado na raiz e timeout de 60 segundos. Initialize real respondeu em 2,56 segundos e tools/list retornou 12 ferramentas. N?o houve instala??o nem encerramento de processos preexistentes. O execut?vel ainda depende da preserva??o desse cache; se ele for removido, ser? necess?rio reconfigurar uma instala??o persistente. Reabrir a sess?o ? necess?rio para carregar a configura??o; esta valida??o isolada n?o comprova recarga da sess?o atual.

## Gate da Etapa 1 remota — revisão do coordenador (2026-10-25)

Gate técnico aprovado para servir de base à Etapa 2, limitado à evidência sintética. A Etapa 0 foi o complemento corretivo da Etapa 1. O worker registrou 194 testes focados e 384 na suíte completa aprovados; o coordenador conferiu as correções no código e nos testes, sem reexecutar a suíte. Homologação física Tailscale/iPad permanece pendente. Recuperação de journal incompleto pode exigir reconciliação manual e não há CAS contra alterações externas no Serve. A Etapa 2 não foi iniciada e exige nova autorização explícita.


## Ferramentas Serena e GitHub — validação de 2026-10-25

O MCP `github` separado falhou nesta sessão com `fetch failed`/timeout de conexão
no endpoint remoto, inclusive pelo iniciador configurado no projeto. A consulta
oficial obrigatória de README/pyproject do Serena via esse MCP não foi concluída;
o conector `codex_apps.github` não foi utilizado. Detalhes da validação Serena e
recarga da sessão no [relatório](PHASE_TOOLING_SERENA_MCP_2026-10-25.md).
