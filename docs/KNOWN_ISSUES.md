# Limitações e problemas conhecidos

Estes itens registram limites atuais do produto. Um problema conhecido não é, por si
só, uma tarefa autorizada; qualquer mudança continua dependente do escopo solicitado.

## Codecs disponíveis

- Descrição: os codecs concretamente disponíveis dependem do FFmpeg incorporado ao PyAV.
- Impacto: uma mídia pode não ser decodificável na distribuição instalada.
- Situação atual: a importação rejeita conteúdo que não consegue validar e decodificar.
- Possível direção futura: validar a matriz real de formatos e codecs suportados.
- Fase provável: Etapa 7, integração e validação real.

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

## Validação real ainda parcial

- Descrição: duas validações reais confirmaram o modelo `small` em CPU `int8`, mas usaram
  apenas gravações curtas em português e não possuíam gabarito textual independente.
- Impacto: o fluxo real está comprovado, porém qualidade, precisão, desempenho em cargas
  maiores e variedade de mídia ainda não foram caracterizados.
- Situação atual: job, segmentos, palavras, métricas, exportações e persistência foram
  verificados. Os RTFs observados foram 1,612 e 0,4778; essa variação e duas amostras
  curtas não caracterizam cargas longas. Nenhuma taxa de precisão foi calculada.
- Possível direção futura: executar uma matriz sanitizada de formatos, durações e gabaritos.
- Fase provável: Etapa 7, integração e validação real.

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
- Fase provável: Etapa 7, integração e validação real.

## Fila persistente ausente

- Descrição: o domínio persiste jobs, mas não implementa uma fila de execução.
- Impacto: não há agendamento nem retomada persistente de processamento.
- Situação atual: fase planejada, não um erro da fundação.
- Possível direção futura: implementar a fila persistente.
- Fase provável: Etapa 4.

## API, SSE e frontend ausentes

- Descrição: a versão atual não oferece API HTTP, eventos SSE nem interface web.
- Impacto: não há uso pelo navegador nem acompanhamento via servidor local.
- Situação atual: componentes planejados para fases posteriores.
- Possível direção futura: FastAPI e SSE, seguidos por frontend vanilla sem CDN.
- Fase provável: API e SSE na Etapa 5; interface web na Etapa 6.
