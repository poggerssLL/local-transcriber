# Validação 3B — Smoke test real da Etapa 3

Este documento registra uma validação posterior ao encerramento da Etapa 3. Ele não altera
o escopo implementado, não inicia a Etapa 4 e não conclui a validação ampla prevista para
a Etapa 7.

## Configuração validada

- modelo Whisper `small` multilíngue, obtido por comando explícito;
- carregamento exclusivamente a partir do runtime local;
- CPU com compute type `int8`;
- idioma português informado explicitamente;
- VAD habilitado;
- timestamps por palavra habilitados;
- áudio curto com aproximadamente 29,85 segundos.

O modelo, a mídia, o banco e as exportações permaneceram fora do Git. Nenhum componente
CUDA, cuDNN ou driver foi instalado ou modificado.

## Resultado técnico

- job concluído com estado `succeeded`;
- processamento persistido de aproximadamente 48,11 segundos;
- fator de tempo real de 1,612;
- pico aproximado do working set do processo Python de 696,6 MiB;
- 4 segmentos e 67 palavras;
- idioma português registrado;
- intervalos de segmentos e palavras monotônicos e confinados à duração do áudio;
- TXT, Markdown, SRT, WebVTT e JSON produzidos e verificados por tamanho e hash;
- gravação, job, transcrição, configurações, métricas e artefatos recuperados em novos
  processos.

A medição de memória usou a API nativa do Windows no próprio processo Python. O tempo e o
RTF de referência são os valores da primeira execução persistida; execuções posteriores
foram influenciadas por caches e não os substituem.

## Qualidade e limites da evidência

A transcrição apresentou alguns erros linguísticos observáveis. Como não havia gabarito
textual independente, não foi calculada nem estimada uma taxa de precisão. Este registro
mantém somente dados técnicos agregados e sanitizados.

CUDA permaneceu sem validação ponta a ponta porque as bibliotecas exigidas não estavam
completamente disponíveis. O teste confirma somente o caminho CPU `int8` para uma amostra
curta em português; matriz de formatos, cargas maiores, precisão com gabarito, desempenho
prolongado e recuperação operacional continuam pertencendo à Etapa 7.

## Conclusão

O fluxo real de download explícito, carregamento local, inferência, persistência e
exportação funcionou conforme a arquitetura da Etapa 3. Nenhuma falha de implementação foi
identificada e nenhuma correção de código foi necessária.
