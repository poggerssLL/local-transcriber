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
- Situação atual: comportamento explícito da versão 0.2.0.
- Possível direção futura: definir política segura de substituição ou versionamento.
- Fase provável: não definida no roadmap atual.

## CLI ausente

- Descrição: ainda não existe interface de linha de comando.
- Impacto: as funcionalidades atuais são consumidas pela API Python.
- Situação atual: fase planejada, não um erro da Etapa 2.
- Possível direção futura: implementar as CLIs previstas.
- Fase provável: Etapa 3.

## Engine Faster Whisper ausente

- Descrição: o primeiro engine de transcrição ainda não foi integrado.
- Impacto: a aplicação não executa transcrição real.
- Situação atual: fase planejada; modelos e engine não foram instalados nem executados.
- Possível direção futura: integrar Faster Whisper com ação explícita para modelos.
- Fase provável: Etapa 3.

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
