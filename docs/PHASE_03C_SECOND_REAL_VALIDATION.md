# Validação 3C — segunda execução real da Etapa 3

Este relatório registra uma segunda validação real, posterior à conclusão funcional da
Etapa 3. A execução não alterou código, arquitetura ou escopo e não iniciou a Etapa 4.

## Configuração validada

- áudio em português com aproximadamente 50,97 segundos;
- modelo `small` multilíngue já instalado no diretório de runtime controlado;
- perfil `cpu`, com tipo de computação efetivo `int8`;
- idioma `pt`, VAD habilitado e timestamps por palavra habilitados.

## Resultado técnico

- o job foi concluído e persistido com sucesso;
- a saída estruturada contém 5 segmentos e 78 palavras;
- o tempo de processamento persistido foi de aproximadamente 24,35 segundos;
- o tempo de parede foi de aproximadamente 25,26 segundos;
- o fator de tempo real (RTF) foi 0,4778, aproximadamente 2,09 vezes mais rápido que
  tempo real;
- o pico aproximado de working set observado foi 709,9 MiB;
- as cinco exportações suportadas foram produzidas e verificadas;
- gravação, job e transcrição permaneceram acessíveis após abrir novos processos da CLI;
- segmentos, palavras e seus intervalos apresentaram estrutura temporal válida;
- os principais números e unidades do conteúdo foram reconhecidos;
- foram observados erros em vocabulário técnico específico;
- não havia gabarito textual independente, portanto nenhuma taxa de precisão foi
  calculada;
- nenhuma falha de implementação foi encontrada.

O conteúdo transcrito, identificadores, caminhos, hashes e demais dados de runtime não
fazem parte deste relatório nem do repositório.

## Comparação com a primeira validação real

A validação 3B registrou RTF 1,612, enquanto esta segunda execução registrou RTF 0,4778.
Caches e o aquecimento do ambiente podem explicar parte da diferença; conteúdo e duração
dos áudios também influenciam o processamento. Duas amostras curtas não permitem garantir
o desempenho de uma gravação de 1h40.

Aplicar o RTF 0,4778 a 1h40 resultaria em uma projeção de aproximadamente 47,8 minutos de
processamento. Essa projeção não é uma medição real de carga longa e não substitui a
validação prolongada, que continua pertencendo à Etapa 7.

## Conclusão

A segunda execução confirmou novamente o fluxo real da Etapa 3 em CPU `int8`, incluindo
inferência, estrutura temporal, métricas, exportações e persistência entre processos. Ela
amplia a evidência prática disponível, sem caracterizar precisão geral, desempenho em
cargas longas ou qualidade para vocabulários especializados.
