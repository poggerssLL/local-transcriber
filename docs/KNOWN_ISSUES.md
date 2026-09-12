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

## Runtime CUDA incompleto no notebook verificado

- Descrição: CTranslate2 encontrou uma GPU, mas `cublas64_12.dll` e
  `cudnn_ops64_9.dll` não estavam carregáveis em 2026-09-09.
- Impacto: o perfil `auto` usa CPU `int8`; CUDA explícita falha com diagnóstico, enquanto
  a inferência CPU real já foi confirmada.
- Situação atual: nenhum runtime ou DLL NVIDIA foi instalado pela aplicação.
- Possível direção futura: instalar CUDA 12/cuBLAS 12/cuDNN 9 por canais oficiais e repetir
  `local-transcriber config check` antes do teste opt-in.
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
