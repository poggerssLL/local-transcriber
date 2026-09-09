# Etapa 3 — Faster Whisper, modelos e CLI

## Resultado

A Etapa 3 integra `faster-whisper==1.2.1` atrás de uma abstração desacoplada, adiciona
gerenciamento explícito de modelos, perfis conservadores de execução e um único comando
`local-transcriber`. A execução continua síncrona: fila, API e interface permanecem fora
desta etapa.

## Arquitetura implementada

- `TranscriptionEngine` define a fronteira independente do backend.
- `FasterWhisperEngine` carrega somente um diretório local com
  `local_files_only=True`, consome completamente os segmentos lazy e converte segmentos e
  palavras para o domínio.
- `TranscriptionService` resolve mídia e modelo controlados, cria o job, mede a execução e
  publica transcrição e sucesso atomicamente.
- `ProgressEvent` oferece callback simples e não persistente para início, segmentos e fim.
- `ModelManager` lista, verifica e instala somente modelos multilíngues suportados em
  `%LOCALAPPDATA%\LocalTranscriber\models`.
- A migração v3 acrescenta a probabilidade do idioma detectado sem alterar migrações antigas.

Configurações efetivas persistidas incluem engine, modelo, idioma solicitado, `beam_size`,
timestamps por palavra, VAD, perfil solicitado, dispositivo e tipo de computação resolvidos.
Métricas incluem duração do áudio, tempo de processamento, segmentos, palavras e fator de
tempo real.

## Política de modelos

Listar ou verificar modelos não acessa a rede. Transcrever também não acessa a rede e falha
antes de criar um job se o modelo estiver ausente. A única operação autorizada a baixar é:

```powershell
local-transcriber models download small --confirm
```

O download usa o mecanismo publicado pelo Faster Whisper, escreve primeiro em diretório
temporário sob `RuntimePaths.models`, verifica os arquivos mínimos e só então publica o
diretório. Nesta etapa, o comando foi testado com downloader injetado; nenhum modelo real
foi baixado.

## Perfis

- `cpu`: exige suporte CTranslate2 a `int8` e nunca tenta CUDA.
- `cuda`: exige dispositivo CUDA, `int8_float16` e bibliotecas necessárias; se faltar algo,
  falha sem fallback.
- `auto`: prefere CUDA somente após a mesma sondagem; caso contrário seleciona CPU `int8` e
  inclui o motivo no evento inicial.

No Windows com CTranslate2 atual, CUDA requer driver compatível, CUDA 12, cuBLAS 12 e cuDNN
9. O projeto não instala essas bibliotecas. Na verificação de 2026-09-09, a GPU foi
enumerada, mas `cublas64_12.dll` e `cudnn_ops64_9.dll` não estavam carregáveis. Assim,
`auto` resolveu corretamente para CPU `int8`.

## CLI

O entrypoint oferece:

- `config check`;
- `subjects add|list`;
- `recordings import|list|delete`;
- `models list|check|download`;
- `transcribe`;
- `transcripts list|show`;
- `export` para TXT, Markdown, SRT, WebVTT e JSON;
- `--help` e `--version`.

Exemplo:

```powershell
local-transcriber transcribe RECORDING_ID --model small --profile auto --language auto
```

## Consistência e falhas

O iterador lazy é consumido enquanto o engine está sob controle do serviço. A transcrição,
seus segmentos e palavras e a transição do job para `succeeded` usam uma única transação.
Se engine, iteração ou persistência falhar, não há publicação parcial; o job recebe estado
`failed` e mensagem técnica de linha única, limitada e sem caminhos físicos do runtime.

## Validação

Foram validados sem rede, GPU ou modelo:

- perfis CPU, CUDA e fallback exclusivo de `auto`;
- confirmação e diretório controlado de modelos;
- ausência de download durante transcrição;
- consumo lazy, segmentos, palavras, idioma, probabilidade e métricas;
- rollback de publicação parcial e erro sanitizado;
- migrações v1/v2 para v3;
- principais superfícies da CLI;
- preservação dos 33 testes anteriores.

Dependências efetivamente instaladas e importadas: Faster Whisper 1.2.1, CTranslate2 4.8.2 e
PyAV 16.1.0 em Python 3.13. Não foram validados: inferência real, qualidade do modelo
`small`, desempenho CPU, uso de VRAM ou inferência CUDA. Nenhum modelo foi baixado.

## Fora desta etapa

Não foram implementados fila persistente, FastAPI, SSE, frontend, microfone ao vivo,
diarização, Ollama, worker remoto ou Home Assistant.
