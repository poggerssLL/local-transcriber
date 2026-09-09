# Etapa 2 — Biblioteca de mídia e exportadores

Esta etapa adiciona importação, inspeção, catálogo, pesquisa e exportação sem
executar transcrição. Todos os dados continuam locais e os arquivos gerenciados
permanecem fora do Git.

## Funcionalidades implementadas

### Biblioteca de mídia

- Cadastro e listagem de matérias.
- Importação a partir de arquivo controlado ou stream binário.
- Cópia progressiva em blocos, sem carregar o arquivo inteiro em memória.
- Cálculo de SHA-256 durante a cópia.
- Detecção de duplicidade exata pelo hash.
- Sanitização de nomes, remoção de diretórios fornecidos e proteção contra nomes
  inválidos no Windows.
- Limites configuráveis de tamanho e extensões permitidas.
- Inspeção real por PyAV e pelas bibliotecas FFmpeg incluídas em sua distribuição.
- Confirmação de stream de áudio, decodificação de ao menos um frame e duração.
- Compatibilidade obrigatória entre a extensão declarada e o contêiner detectado.
- Rejeição de arquivos corrompidos, conteúdo não decodificável e vídeo sem áudio.
- Armazenamento em caminhos relativos abaixo de `media/`.
- Listagem e exclusão explícita, incluindo metadados relacionados.

As extensões aceitas são WAV, MP3, FLAC, M4A, OGG, MP4, MKV e WebM. A extensão é
apenas a primeira barreira: o conteúdo precisa ser aberto e decodificado pelo PyAV.
Um WAV renomeado para `.mp3`, por exemplo, também é rejeitado.

### Pesquisa

A pesquisa textual usa SQLite FTS5 com o tokenizador Unicode e remoção de
diacríticos. O índice cobre:

- título da gravação;
- nome da matéria;
- conteúdo de transcrições presentes ou futuras.

Triggers mantêm o índice sincronizado quando gravações, matérias ou transcrições
são inseridas, alteradas ou removidas. As consultas transformam a entrada em tokens
citados e continuam parametrizadas.

### Modelos estruturados

Além de transcrição, segmento e palavra, o domínio agora inclui:

- `TranscriptionSettings`: engine, modelo, idioma, beam size e timestamps por palavra;
- `TranscriptionMetrics`: duração do áudio, tempo de processamento, contagens e
  fator de tempo real calculado;
- `ExportedArtifact`: tipo, MIME type, tamanho, SHA-256 e caminho relativo;
- `MediaImportSettings` e `MediaInfo` para limites e resultado da inspeção;
- `RecordingSearchResult` para resultados de busca sem expor caminhos físicos.

Os segmentos são canonicalizados por ordinal, garantindo reconstrução e exportação
estáveis mesmo quando a entrada chega fora de ordem.

### Exportadores

Os exportadores determinísticos produzem UTF-8 com quebras de linha `LF`:

- TXT;
- Markdown;
- SubRip/SRT;
- WebVTT;
- JSON estruturado.

SRT usa vírgula nos milissegundos e WebVTT usa ponto. A conversão arredonda para o
milissegundo mais próximo com regra explícita. Markdown neutraliza marcação e HTML
fornecidos como conteúdo, e WebVTT escapa `&`, `<` e `>`. O JSON usa chaves
ordenadas, preserva Unicode e nunca inclui caminhos do sistema.

## Decisões arquiteturais

A importação usa primeiro um arquivo temporário em `media/.incoming`. Somente após
hash, verificação de duplicidade e inspeção bem-sucedida ele é movido atomicamente
para seu destino definitivo. Se a gravação dos metadados falhar, o arquivo final é
removido. Temporários também são limpos em falhas de tamanho ou decodificação.

O destino combina ano, UUID da gravação e nome sanitizado:

```text
media/<ano>/<recording-id>/<nome-seguro.ext>
```

A exclusão renomeia primeiro o arquivo para um nome transitório, remove os registros
em transação e só então apaga o arquivo. Se o banco falhar, o arquivo é restaurado.

Os renderizadores são funções puras que retornam bytes. `TranscriptExporter` é uma
camada separada para gravar esses bytes sob `exports/` e registrar tamanho, hash e
tipo MIME no SQLite.

## Migração do banco

O schema publicado na Etapa 1 continua sendo o schema v1, sem alterações
retroativas. `SCHEMA_VERSION` agora é 2, e a migração v2 é aplicada depois da v1 em
bancos vazios ou diretamente sobre bancos v1 existentes.

A migração v2 adiciona:

- `transcripts.settings_json`;
- `transcripts.metrics_json`;
- `exported_artifacts.media_type`;
- `exported_artifacts.size_bytes`;
- `exported_artifacts.sha256`;
- tabela virtual FTS5 `recording_search`;
- população inicial do índice com registros v1 existentes;
- triggers de sincronização do índice.

As migrações executam em transações, gravam `PRAGMA user_version = 2` somente ao
concluir e são idempotentes após a versão ser registrada. Há testes para banco vazio
e para banco v1 já preenchido, incluindo preservação e indexação dos registros.

## Arquivos criados ou modificados

Criados:

- `src/local_transcriber/media.py`;
- `src/local_transcriber/exporters.py`;
- `tests/test_media.py`;
- `tests/test_exporters.py`;
- `tests/test_migrations_and_search.py`;
- `docs/PHASE_02_MEDIA_LIBRARY.md`.

Modificados:

- `src/local_transcriber/database.py`;
- `src/local_transcriber/models.py`;
- `src/local_transcriber/repository.py`;
- `src/local_transcriber/__init__.py`;
- `pyproject.toml`;
- `README.md`.

## Utilização

Instalação:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Importação:

```python
from datetime import date

from local_transcriber import AppConfig, Database, MediaLibrary, Repository

config = AppConfig.from_env()
database = Database(config.paths.database)
database.initialize()
library = MediaLibrary(Repository(database), config.paths)

subject = library.create_subject("História")
recording = library.import_file(
    r"C:\entrada\aula.m4a",
    title="Revolução Industrial",
    subject_id=subject.id,
    lesson_date=date(2026, 9, 9),
)
```

Pesquisa e exclusão explícita:

```python
results = library.repository.search_recordings("revolução industrial")
removed = library.delete_recording(recording.id)
```

Renderização sem gravar arquivos:

```python
from local_transcriber import ExportFormat, render_transcript

content = render_transcript(transcript, ExportFormat.WEBVTT)
```

Gravação gerenciada de um artefato:

```python
from local_transcriber import TranscriptExporter

artifact = TranscriptExporter(library.repository, config.paths).export(
    transcript, ExportFormat.JSON
)
```

Não foi adicionada uma CLI nesta etapa; ela está prevista junto ao engine na Etapa 3.

## Testes e validações

Os testes usam transcrições artificiais, WAV gerado em memória e um MKV sintético
sem áudio. Eles cobrem:

- mídia válida por stream e arquivo;
- arquivo inválido e extensão não permitida;
- vídeo sem áudio;
- duplicidade por SHA-256;
- limite durante cópia progressiva;
- sanitização e path traversal;
- listagem e exclusão;
- migração v1 para v2 e banco vazio;
- FTS5 em título, matéria e conteúdo de transcrição;
- ordenação, timestamps e escaping;
- UTF-8 e português;
- TXT, Markdown, SRT, WebVTT e JSON;
- caminhos relativos e ausência de caminhos absolutos nos resultados exportados.

Comandos de validação:

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\python -m compileall -q src tests
.venv\Scripts\python -m pip check
```

## Limitações conhecidas

- A disponibilidade concreta de codecs depende da distribuição FFmpeg embarcada
  no wheel do PyAV instalado.
- Duplicidade significa igualdade exata dos bytes, não equivalência perceptual.
- A biblioteca não converte, normaliza ou edita mídia.
- Não há recuperação automática após queda de energia entre uma operação de arquivo
  e sua transação SQLite; os fluxos normais de exceção fazem compensação.
- A pesquisa não oferece ranking ou filtros avançados além do FTS5 e do limite.
- Exportar novamente o mesmo formato para a mesma transcrição exige gestão explícita
  do artefato existente nesta versão.

## Preparação para a próxima etapa

Os modelos de configurações e métricas, os caminhos gerenciados, a validação de
áudio e os resultados estruturados deixam os limites necessários para integrar o
primeiro engine `faster-whisper` e futuras CLIs. O engine e suas dependências não
foram instalados nem executados nesta etapa.

Também não foram implementados fila persistente, FastAPI, SSE ou interface web.
