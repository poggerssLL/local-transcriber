# Local Transcriber

Fundação local para catalogar gravações e persistir o ciclo de vida de futuras
transcrições. Esta etapa contém somente configuração, modelos de domínio e SQLite;
não lê mídia nem executa transcrição.

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
from local_transcriber import AppConfig, Database, Repository

config = AppConfig.from_env()
config.paths.ensure_directories()
database = Database(config.paths.database)
database.initialize()
repository = Repository(database)
```

Consulte [o contrato do projeto](docs/PROJECT_CONTRACT.md) e o
[roadmap](docs/ROADMAP.md) antes de ampliar o escopo.
