# Arquitetura técnica do Local Transcriber

> Documento vivo e cumulativo da arquitetura atual. Os relatórios `PHASE_XX_*.md`
> preservam o estado histórico de cada etapa; esta visão deve acompanhar o sistema.

## Finalidade e estado

O **Local Transcriber** é uma aplicação local para catalogar gravações, executar
transcrição com Faster Whisper e exportar resultados estruturados sem depender de APIs
de IA em nuvem. A versão atual é `0.3.0`, usa schema SQLite v3 e concluiu:

1. fundação e persistência;
2. biblioteca de mídia, pesquisa e exportadores;
3. Faster Whisper, modelos explícitos e CLI.

A próxima etapa planejada é a fila persistente. API, SSE, interface web, diarização,
Ollama, microfone ao vivo e Home Assistant ainda não foram implementados.

## Estrutura do repositório

```text
Local Transcriber/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── docs/
│   ├── FOUNDATION.md
│   ├── PROJECT_CONTRACT.md
│   ├── PROJECT_STATE.md
│   ├── ROADMAP.md
│   ├── DECISIONS.md
│   ├── KNOWN_ISSUES.md
│   └── PHASE_XX_*.md
├── src/local_transcriber/
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── repository.py
│   ├── media.py
│   ├── exporters.py
│   ├── models_manager.py
│   ├── transcription.py
│   ├── cli.py
│   └── __main__.py
└── tests/
```

O pacote usa layout `src/`, Python 3.11 ou superior e um único entrypoint instalável,
`local-transcriber`.

## Componentes e responsabilidades

- `config.py`: resolve configuração, diretórios de runtime e caminhos relativos seguros.
- `models.py`: define modelos de domínio imutáveis e suas validações.
- `database.py`: abre conexões SQLite e aplica migrações incrementais.
- `repository.py`: executa consultas parametrizadas e reconstrói o domínio.
- `media.py`: importa, inspeciona, cataloga e exclui mídia gerenciada.
- `exporters.py`: renderiza formatos determinísticos e registra artefatos.
- `models_manager.py`: lista, verifica e baixa modelos somente mediante confirmação.
- `transcription.py`: abstrai o engine, resolve perfis e coordena a transcrição.
- `cli.py`: expõe os serviços existentes sem duplicar regras de negócio.

## Configuração e RuntimePaths

`AppConfig.from_env()` usa `%LOCALAPPDATA%\LocalTranscriber` por padrão. Em testes ou
desenvolvimento, `LOCAL_TRANSCRIBER_DATA_DIR` pode indicar outro diretório absoluto.
`RuntimePaths` fornece:

```text
LocalTranscriber/
├── local_transcriber.sqlite3
├── media/
├── exports/
└── models/
```

Os diretórios são criados explicitamente, não durante a importação do pacote. Caminhos
persistidos usam `/`, são relativos ao runtime e rejeitam valores absolutos, prefixos de
unidade, barras invertidas e componentes `..`. A resolução final confirma confinamento.

Áudios, vídeos, modelos, bancos, transcrições pessoais, exportações, caches e temporários
permanecem fora do repositório e são bloqueados pelo `.gitignore`.

## Domínio e persistência

Os principais modelos são:

- `Subject`: matéria associada a gravações;
- `Recording`: metadados, hash, duração e caminho relativo da mídia;
- `TranscriptionJob`: ciclo `pending`, `running`, `succeeded`, `failed` ou `cancelled`;
- `Transcript`: texto, idioma, probabilidade, configurações, métricas e segmentos;
- `Segment` e `Word`: intervalos temporais ordenados, com probabilidade opcional;
- `ExportedArtifact`: formato, MIME type, tamanho, hash e caminho relativo;
- `TranscriptionSettings` e `TranscriptionMetrics`: parâmetros efetivos e desempenho.

Identificadores são UUIDs, datas de criação usam UTC e os modelos validam intervalos,
probabilidades, hashes, nomes e estados antes da persistência.

SQLite armazena somente metadados. O schema v1 criou o domínio persistente; o v2 adicionou
configurações, métricas, metadados de exportação e FTS5; o v3 acrescentou a probabilidade
do idioma detectado. Migrações publicadas são imutáveis, incrementais e testadas em banco
vazio e existente. Chaves estrangeiras são habilitadas em cada conexão e todo conteúdo
variável chega ao SQL por parâmetros.

## Biblioteca e inspeção de mídia

`MediaLibrary` aceita arquivo controlado ou stream binário. A importação:

1. sanitiza o nome e valida extensão e limites;
2. copia em blocos para `media/.incoming`, calculando SHA-256;
3. rejeita duplicidade exata dos bytes;
4. usa PyAV/FFmpeg para confirmar contêiner, stream de áudio e decodificação;
5. move atomicamente o temporário para `media/<ano>/<uuid>/<nome>`;
6. persiste os metadados e compensa o arquivo se o banco falhar.

WAV, MP3, FLAC, M4A, OGG, MP4, MKV e WebM são extensões aceitas, mas a aceitação real
depende do contêiner e dos codecs disponíveis no PyAV instalado. Não há conversão,
normalização ou equivalência perceptual.

## Pesquisa e exportação

A pesquisa local usa SQLite FTS5 com tokenização Unicode e remoção de diacríticos.
Triggers mantêm título, matéria e conteúdo transcrito sincronizados. As consultas são
parametrizadas. Ranking e filtros avançados ainda são limitações conhecidas.

Renderizadores puros produzem bytes UTF-8 determinísticos com quebras `LF` em TXT,
Markdown, SRT, WebVTT e JSON. SRT e WebVTT aplicam convenções próprias de milissegundos;
Markdown e WebVTT escapam conteúdo. `TranscriptExporter` grava sob `exports/` e registra
tipo, tamanho e SHA-256 no SQLite.

## Modelos e Faster Whisper

`ModelManager` suporta somente a lista multilíngue aprovada. Listagem e verificação não
usam rede. Download só ocorre por comando explícito com `--confirm`, primeiro em
diretório temporário sob `RuntimePaths.models` e depois no destino final verificado.

Uma transcrição comum exige que o modelo já esteja instalado. `FasterWhisperEngine` abre
o diretório local com `local_files_only=True`, impedindo download implícito. A integração
validada usa Faster Whisper 1.2.1, CTranslate2 4.8.2 e PyAV 16.1.0.

## Perfis de execução

- `cpu`: seleciona CPU com `int8`.
- `cuda`: exige dispositivo e runtime aprovados, usa `int8_float16` e nunca faz fallback.
- `auto`: prefere CUDA somente após a sondagem; caso contrário usa CPU `int8` e registra
  o motivo.

No Windows, a sondagem verifica CTranslate2 e as bibliotecas necessárias. A presença da
GPU não prova disponibilidade de CUDA/cuDNN. As validações reais 3B e 3C validaram apenas
CPU `int8`; CUDA continua sem validação ponta a ponta.

## Abstração e serviço de transcrição

`TranscriptionEngine` é um `Protocol` que desacopla o domínio do backend. O adaptador
`FasterWhisperEngine` recebe mídia e modelo controlados, aplica idioma, beam size,
timestamps por palavra e VAD, consome integralmente o iterador lazy e converte a saída
em `Segment`, `Word`, idioma detectado e probabilidade.

`TranscriptionService` coordena o fluxo:

```text
gravação catalogada
  → modelo local verificado
  → perfil resolvido
  → job pending/running
  → engine consome todos os segmentos
  → Transcript + métricas
  → publicação transacional
  → job succeeded
  → exportações gerenciadas
```

Eventos simples e não persistentes informam início, segmentos e conclusão. Eles preparam
integrações futuras sem implementar uma fila.

A transcrição, seus segmentos e palavras e a mudança do job para `succeeded` são
publicados na mesma transação. Falhas não publicam resultado parcial; o job recebe
`failed` com erro técnico sanitizado. Uma queda abrupta entre filesystem e SQLite ainda
pode exigir reconciliação futura.

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

A CLI compõe `MediaLibrary`, `Repository`, `ModelManager`, `TranscriptionService` e
`TranscriptExporter`; ela não replica suas regras.

## Evidência de validação

### Automatizada e com doubles

A suíte de 48 testes funciona sem GPU, modelo ou rede. Ela cobre configuração, domínio,
migrações, mídia sintética, pesquisa, exportadores, perfis, ausência de download
automático, backend injetado, consumo lazy, falhas transacionais e comandos principais
da CLI. Esses testes validam comportamento determinístico, não qualidade de inferência.

### Execução real

As validações 3B e 3C executaram duas gravações curtas em português com o modelo `small`
multilíngue, CPU `int8`, VAD e timestamps por palavra. Em ambas, o job concluiu, gerou
segmentos e palavras, persistiu métricas, produziu os cinco formatos e foi recuperado em
novos processos. A primeira execução registrou RTF 1,612. A segunda registrou RTF 0,4778,
aproximadamente 2,09 vezes mais rápida que tempo real, com pico aproximado de working set
de 709,9 MiB. Caches, aquecimento, conteúdo e duração podem influenciar essa diferença.

Na segunda execução, a estrutura temporal e os números principais foram validados, mas
houve erros em vocabulário técnico específico. Nenhuma das amostras possuía gabarito
textual independente, portanto nenhuma taxa de precisão foi calculada. Nenhum defeito de
implementação foi identificado.

Essa evidência não conclui a Etapa 7: duas amostras curtas não garantem desempenho em uma
gravação de 1h40. O RTF 0,4778 projetaria aproximadamente 47,8 minutos para essa duração,
mas não constitui medição real de carga longa. Ainda faltam validação ampla de formatos,
qualidade, desempenho, recuperação operacional e CUDA em configuração compatível.

## Limitações e trabalho futuro

- codecs concretos dependem do PyAV/FFmpeg instalado;
- duplicidade é somente por bytes;
- não há conversão ou normalização de mídia;
- não há reconciliação automática após interrupção abrupta;
- pesquisa não possui ranking ou filtros avançados;
- reexportação do mesmo formato exige gestão explícita;
- qualidade foi observada sem gabarito independente, e vocabulário técnico específico
  ainda pode apresentar erros;
- qualquer adaptação contextual futura exige escopo próprio e avaliação com gabarito;
- CUDA não foi validada ponta a ponta;
- fila persistente, API, SSE e interface web ainda não existem;
- diarização, Ollama, microfone ao vivo e Home Assistant permanecem fora do MVP.

Consulte [estado atual](PROJECT_STATE.md), [decisões](DECISIONS.md),
[problemas conhecidos](KNOWN_ISSUES.md), [roadmap](ROADMAP.md) e os relatórios
[Etapa 1](PHASE_01_FOUNDATION.md), [Etapa 2](PHASE_02_MEDIA_LIBRARY.md),
[Etapa 3](PHASE_03_WHISPER_AND_CLI.md), [validação 3B](PHASE_03B_REAL_VALIDATION.md) e
[validação 3C](PHASE_03C_SECOND_REAL_VALIDATION.md).
