# Etapa 1 — Fundação e persistência

> Relatório histórico preservado da primeira etapa. As referências a versão 0.1.0,
> schema v1, 15 testes e funcionalidades ainda ausentes descrevem o estado naquele
> encerramento e não devem ser interpretadas como o estado atual do produto.

# Fundação do Local Transcriber

Este documento descreve a primeira etapa do **Local Transcriber**. O objetivo foi
criar uma base segura e testada para as fases futuras, sem implementar leitura de
mídia, transcrição, fila, API ou interface web.

## Resultado da etapa

O projeto é um pacote Python instalável com:

- configuração tipada e resolução segura do diretório de dados;
- modelos de domínio imutáveis e validados;
- banco SQLite com integridade referencial e schema versionado;
- operações básicas de persistência;
- testes de caminhos, Unicode, reinicialização, SQL parametrizado e valores inválidos;
- documentação dos invariantes e do roadmap.

O runtime fica fora do repositório. Por padrão, seus dados são armazenados em:

```text
%LOCALAPPDATA%\LocalTranscriber
```

## Estrutura do projeto

```text
Local Transcriber/
├── .gitignore
├── README.md
├── pyproject.toml
├── docs/
│   ├── FOUNDATION.md
│   ├── PROJECT_CONTRACT.md
│   └── ROADMAP.md
├── src/local_transcriber/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   └── repository.py
└── tests/
    ├── test_config.py
    └── test_persistence.py
```

O ambiente virtual próprio fica em `.venv/` e é ignorado pelo Git.

## Empacotamento Python

O `pyproject.toml` define o pacote `local-transcriber`, versão `0.1.0`, com Python
3.11 ou superior e layout `src/`. O projeto usa `setuptools` para build e não tem
dependências de runtime nesta fase. `pytest` e `ruff` são dependências opcionais de
desenvolvimento.

Instalação para desenvolvimento:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

## Configuração e caminhos de runtime

`AppConfig.from_env()` resolve o diretório de dados a partir de `%LOCALAPPDATA%`.
Para testes ou desenvolvimento, a variável `LOCAL_TRANSCRIBER_DATA_DIR` permite
usar outro diretório absoluto.

A estrutura preparada para o runtime é:

```text
LocalTranscriber/
├── local_transcriber.sqlite3
├── media/
├── exports/
└── models/
```

Os diretórios só são criados quando `RuntimePaths.ensure_directories()` é chamado.
Isso evita efeitos colaterais ao importar o pacote.

Os caminhos persistidos para mídia e artefatos são relativos e usam `/`, por
exemplo `media/2026/aula-01.m4a`. A validação rejeita caminhos absolutos, prefixos
de unidade, valores vazios, barras invertidas e componentes `..`. A resolução final
também confirma que o arquivo continua dentro do diretório de runtime.

## Modelos de domínio

Os modelos são dataclasses tipadas, imutáveis e com `slots`. Identificadores são
UUIDs e datas de criação usam UTC.

### Matéria

`Subject` representa uma matéria com identificador, nome e data de criação. Nomes
vazios ou formados apenas por espaços são rejeitados.

### Gravação

`Recording` registra:

- título e matéria;
- data da aula;
- nome original;
- hash SHA-256;
- tamanho em bytes;
- formato e duração opcional;
- caminho relativo controlado;
- identificador e data de criação.

O hash precisa ter 64 caracteres hexadecimais. Tamanho e duração não podem ser
negativos, e o nome original deve ser apenas um nome de arquivo. O áudio não é
armazenado no SQLite como BLOB: o banco guarda apenas metadados e o caminho.

### Job de transcrição

`TranscriptionJob` prepara o ciclo de vida da futura execução. Os estados válidos
são `pending`, `running`, `succeeded`, `failed` e `cancelled`.

As transições permitidas são:

```text
pending → running
pending → cancelled
running → succeeded
running → failed
running → cancelled
```

Um job com estado `failed` exige uma mensagem de erro. Estados finais não voltam
para estados anteriores. Essa estrutura não implementa uma fila; apenas prepara
sua persistência para uma fase futura.

### Transcrição, segmentos e palavras

`Transcript` contém a gravação, o job responsável, idioma opcional, texto completo
e seus segmentos. Cada job pode produzir no máximo uma transcrição.

Cada `Segment` tem posição ordinal, início, fim, texto e palavras opcionais. Cada
`Word` pode incluir sua probabilidade. Os intervalos precisam obedecer a
`0 <= início <= fim`, e probabilidades devem estar entre 0 e 1.

### Artefatos exportados

`ExportedArtifact` registra a transcrição de origem, o tipo do arquivo e seu caminho
relativo seguro. Nesta etapa há somente o registro; os exportadores serão criados
posteriormente.

## Banco SQLite

O schema inicial cria as tabelas:

- `subjects`;
- `recordings`;
- `transcription_jobs`;
- `transcripts`;
- `segments`;
- `words`;
- `exported_artifacts`.

O relacionamento principal é:

```text
matéria
└── gravações
    ├── jobs de transcrição
    └── transcrição
        ├── segmentos
        │   └── palavras opcionais
        └── artefatos exportados
```

As chaves estrangeiras são habilitadas em cada conexão. O schema também impõe
restrições para estados, valores não negativos, probabilidades, ordinais únicos,
hashes e caminhos únicos. Índices apoiam consultas por matéria/data, gravação/estado
e transcrição/ordem dos segmentos.

## Versionamento e transações

A versão atual é `SCHEMA_VERSION = 1`, registrada por `PRAGMA user_version`. A
inicialização cria o banco se necessário, aplica a migração atomicamente e não
repete trabalho quando executada novamente. Um banco com schema mais novo que o
código é rejeitado para evitar corrupção acidental.

Conexões são fechadas explicitamente. Escritas usam transações com `commit` no
sucesso e `rollback` em caso de erro. A transcrição, seus segmentos e suas palavras
são persistidos como uma única unidade.

## Operações de persistência

`Repository` oferece operações básicas para:

- criar, obter e listar matérias;
- criar, obter e listar gravações;
- filtrar gravações por matéria;
- criar, obter e atualizar jobs;
- criar e reconstruir transcrições com segmentos e palavras;
- criar e listar artefatos exportados.

Todas as entradas variáveis são enviadas ao SQLite como parâmetros `?`, sem
concatenação de conteúdo do usuário no SQL.

## Proteção de dados no Git

O `.gitignore` exclui ambientes virtuais, caches, builds, `.env`, runtime, uploads,
modelos, bancos SQLite, mídias e transcrições exportadas. Extensões de áudio, vídeo,
legenda e banco também são bloqueadas explicitamente.

Isso reforça o contrato de que uploads, modelos, bancos, áudios, vídeos e
transcrições pessoais nunca devem entrar no Git.

## Validação executada

Os 15 testes automatizados cobrem:

- criação do banco e versão do schema;
- migração idempotente;
- operações essenciais e relacionamentos;
- reinicialização preservando registros;
- resolução e rejeição de caminhos;
- Unicode em matérias, transcrições e palavras;
- consultas parametrizadas contra entradas semelhantes a SQL injection;
- integridade de chaves estrangeiras;
- hashes, timestamps, probabilidades, estados e transições inválidas.

Também passaram a verificação de lint, a conferência de formatação, a compilação de
sintaxe e `pip check` sem dependências quebradas.

## Limites desta etapa

Ainda não foram implementados:

- leitura ou análise de mídia;
- Faster Whisper e download de modelos;
- transcrição real;
- fila persistente;
- FastAPI ou SSE;
- frontend;
- diarização, Ollama, microfone ao vivo ou Home Assistant.

Essas decisões estão registradas no [contrato do projeto](PROJECT_CONTRACT.md), e a
ordem planejada de implementação está no [roadmap](ROADMAP.md).
