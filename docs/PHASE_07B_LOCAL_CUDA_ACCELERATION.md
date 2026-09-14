# Etapa 7B — Aceleração CUDA local

> Registro histórico da conclusão da correção complementar 7B em 2026-09-14. Não contém
> conteúdo, nomes, caminhos, hashes ou identificadores de mídias e runtimes locais.

## Escopo concluído

A 7B habilitou e validou a aceleração CUDA local do Faster Whisper no Windows para a
configuração já usada pelo projeto. Também corrigiu uma condição observada durante a
validação operacional: uma tentativa de excluir uma gravação com job ativo podia remover o
job já reivindicado e interromper o worker. A versão passou a `0.7.1`; o schema SQLite
permanece v4, sem migração.

Não foram iniciadas a Etapa 8, worker remoto, diarização, Ollama, microfone, Home
Assistant ou qualquer download automático de modelo. O projeto não baixou modelos nem
alterou configurações globais do Windows ou do OneDrive.

## Compatibilidade e instalação local verificada

O ambiente usa Faster Whisper 1.2.1 e CTranslate2 4.8.2. A GPU observada foi uma NVIDIA
RTX 2050 com 4 GiB de memória e capacidade de computação 8.6. O driver informado pelo
sistema foi 581.29. A indicação de CUDA 13 pelo `nvidia-smi` foi tratada somente como
capacidade do driver, não como runtime escolhido pelo projeto.

Foram instalados explicitamente pelo operador, a partir de fontes oficiais da NVIDIA:

- CUDA Toolkit 12.8.2, incluindo o componente cuBLAS para CUDA 12;
- cuDNN 9.26.0.51 para CUDA 12 em Windows x86-64.

As fontes consultadas foram o [arquivo de downloads CUDA 12.8.2](https://developer.nvidia.com/cuda-12-8-2-download-archive), o
[manifesto oficial CUDA 12.8.2](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.8.2.json), a
[página oficial de downloads do cuDNN](https://developer.nvidia.com/cudnn-downloads), o
[manifesto cuDNN 9.26.0](https://developer.download.nvidia.com/compute/cudnn/redist/redistrib_9.26.0.json), o
[guia CUDA para Windows](https://docs.nvidia.com/cuda/cuda-installation-guide-microsoft-windows/) e a
[matriz de suporte do cuDNN](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/support-matrix.html).
O driver não foi substituído e não foi adotado CUDA 13.

## Descoberta das DLLs sem alteração global

Os instaladores gráficos da NVIDIA podem não inserir o diretório de binários do cuDNN no
`PATH`. Além disso, o Python moderno restringe a busca de DLLs de extensões nativas. A
aplicação passou a localizar, apenas no processo atual, os diretórios padrão de instalação
da NVIDIA que contêm `cublas64_12.dll` e `cudnn64_9.dll`.

- A busca aceita somente CUDA `v12.*` e cuDNN `v9.*` sob os diretórios padrão da NVIDIA.
- Cada diretório é registrado uma vez com `os.add_dll_directory`, e seu handle é mantido
  vivo pelo processo.
- A configuração acontece antes de importar CTranslate2 e antes da verificação das DLLs.
- Nenhuma variável de ambiente global, `PATH`, DLL avulsa ou diretório arbitrário fornecido
  pelo usuário é usado.

Após a correção, `local-transcriber config check` identificou um dispositivo CUDA e os
tipos suportados `bfloat16`, `float16`, `float32`, `int8`, `int8_bfloat16`,
`int8_float16` e `int8_float32`, sem erro de runtime.

## Execução real controlada

Uma mesma amostra curta controlada, sem conteúdo registrado neste documento, foi executada
com o modelo `small`, idioma automático, beam size 5, VAD e timestamps por palavra. A
comparação inclui carregamento do modelo e processamento local; não é benchmark para
gravações longas.

| Medida | CPU `int8` | CUDA `int8_float16` |
| --- | ---: | ---: |
| Duração da mídia | 33,97 s | 33,97 s |
| Processamento persistido | 118,32 s | 19,79 s |
| Tempo de parede observado | 118,37 s | 20,29 s |
| RTF aproximado | 3,482 | 0,583 |

Nesta execução específica, a amostra não produziu segmentos ou palavras, portanto ela
confirma execução e publicação do job, mas não caracteriza reconhecimento de fala. A
amostragem durante o job CUDA observou pico aproximado de 1.460 MiB de memória de GPU em
60 coletas. Não foram coletadas séries de temperatura ou utilização suficientes para
afirmar picos térmicos.

Posteriormente, o operador informou ter testado áudios com CUDA. Essa é evidência
operacional fornecida pelo operador; não foram coletados por esta entrega conteúdo,
métricas, segmentos ou avaliação independente desses testes.

## Proteção da fila durante exclusão

A exclusão de gravação agora abre transação imediata e rejeita a operação com HTTP 409
quando existe job `pending` ou `running`. A gravação, a mídia e o job permanecem
preservados. Se um job reivindicado deixar de existir por circunstância excepcional, a
camada de repositório e o serviço tratam o caso como `LeaseOwnershipLost`; o worker não
usa mais uma asserção que poderia encerrá-lo.

Isso preserva as garantias da correção 5C: polling ocioso sem transação de escrita e
retries SQLite curtos e limitados. Não alterou estados públicos, leases, contratos `/api`
nem o schema v4.

## Validação

### Automatizada e com doubles

- 67 testes direcionados de transcrição, fila, mídia e API aprovados;
- 6 regressões de contenção SQLite da 5C aprovadas;
- suíte Python completa: 115 testes aprovados;
- 11 testes JavaScript comportamentais aprovados.

Os novos doubles cobrem descoberta de diretórios padrão, registro único de DLLs,
configuração anterior à importação de CTranslate2, rejeição de exclusão com job pendente,
exclusão concorrente a job reivindicado e continuidade do worker no lifespan da API. Eles
não medem qualidade ou desempenho de inferência.

### Execução local real

- `config check` confirmou o runtime CUDA carregável;
- a comparação CPU/CUDA acima executou job real pela fila local;
- o operador realizou teste posterior de áudios por CUDA, sem telemetria recolhida;
- a inicialização local vazia, saúde, OpenAPI, ausência de `/api/docs` e `/redoc` e a
  liberação da porta após o teste foram verificados sem inferência adicional nem acesso de
  rede.

Os testes Python usaram `--basetemp` fora do checkout sincronizado. Não ocorreu
`PermissionError` nessa validação; portanto não houve ajuste para ocultar falha do
OneDrive.

## Limitações e reversão

- A evidência CUDA cobre `small` e uma amostra curta; modelos maiores, cargas longas,
  diversos codecs e estabilidade térmica não foram caracterizados.
- Não há gabarito textual independente, portanto não existe taxa de precisão declarada.
- O perfil `cuda` continua sem fallback silencioso; `auto` escolhe CPU `int8` se a
  sondagem CUDA falhar.
- Para reverter a mudança do projeto, basta restaurar esta versão do código; ela não
  deixou alterações globais de `PATH` ou arquivos de DLL no runtime do projeto.
- Para remover os componentes NVIDIA, use os desinstaladores oficiais do Windows, fora
  deste repositório. O perfil CPU continua disponível.
