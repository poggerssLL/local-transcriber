# Local Transcriber

Aplicação local para catalogar gravações e persistir o ciclo de vida de futuras
transcrições. A versão atual inclui importação segura e inspeção de mídia, pesquisa
SQLite FTS5 e exportadores de transcrições artificiais. Ainda não executa transcrição.

## Requisitos e instalação

- Windows e Python 3.11 ou superior.
- Nenhum serviço externo é necessário.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Por padrão, os dados ficam em `%LOCALAPPDATA%\LocalTranscriber`. Para testes ou
desenvolvimento, `LOCAL_TRANSCRIBER_DATA_DIR` pode apontar para outro diretório
absoluto. O diretório é criado apenas quando `RuntimePaths.ensure_directories()`
é chamado.

## Exemplo mínimo

```python
from local_transcriber import AppConfig, Database, MediaLibrary, Repository

config = AppConfig.from_env()
config.paths.ensure_directories()
database = Database(config.paths.database)
database.initialize()
repository = Repository(database)
library = MediaLibrary(repository, config.paths)
```

## Contexto para contribuidores

- [AGENTS.md](AGENTS.md): regras obrigatórias para qualquer tarefa neste repositório.
- [Contrato do projeto](docs/PROJECT_CONTRACT.md): invariantes permanentes do produto.
- [Estado atual](docs/PROJECT_STATE.md): fotografia curta da versão e das capacidades atuais.
- [Roadmap](docs/ROADMAP.md): sequência autorizada das fases do projeto.
- [Decisões arquiteturais](docs/DECISIONS.md): escolhas confirmadas, motivos e consequências.
- [Problemas conhecidos](docs/KNOWN_ISSUES.md): limitações atuais sem autorização implícita para corrigi-las.
- [Fundação](docs/FOUNDATION.md): relatório histórico da Etapa 1.
- [Biblioteca de mídia e exportadores](docs/PHASE_02_MEDIA_LIBRARY.md): relatório histórico da Etapa 2.
