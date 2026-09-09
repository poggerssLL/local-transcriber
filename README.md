# Local Transcriber

Aplicação local para catalogar gravações e executar transcrição com Faster Whisper.
A versão atual inclui importação segura e inspeção de mídia, pesquisa SQLite FTS5,
transcrição local síncrona e exportadores TXT, Markdown, SRT, WebVTT e JSON.

## Requisitos e instalação

- Windows e Python 3.11 ou superior.
- Nenhum serviço externo é necessário.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

As versões validadas na Etapa 3 foram `faster-whisper==1.2.1`,
`ctranslate2==4.8.2` e `av==16.1.0` em Python 3.13 no Windows.

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

## CLI

O pacote instala um único comando:

```powershell
local-transcriber --help
local-transcriber --version
local-transcriber config check
local-transcriber subjects add "Língua Portuguesa"
local-transcriber subjects list
local-transcriber recordings import C:\entrada\aula.m4a --title "Aula 1" --subject ID --date 2026-09-09
local-transcriber recordings list
local-transcriber recordings delete ID --confirm
local-transcriber models list
local-transcriber models check small
local-transcriber models download small --confirm
local-transcriber transcribe ID --model small --profile auto --language auto
local-transcriber transcripts list
local-transcriber transcripts show ID
local-transcriber export ID --format srt
```

`models download` é a única operação que pode obter um modelo e exige `--confirm`.
Uma transcrição comum abre exclusivamente o diretório já instalado com
`local_files_only=True`; se o modelo estiver ausente, o comando falha sem acessar a rede.

Perfis de execução:

- `cpu`: CPU com `int8`;
- `cuda`: NVIDIA com `int8_float16`, sem fallback, após a sondagem do runtime;
- `auto`: usa CUDA somente quando o dispositivo, o tipo de computação e as DLLs exigidas
  estão disponíveis; caso contrário usa CPU `int8` e informa o motivo.

No Windows, o runtime atual do Faster Whisper/CTranslate2 exige CUDA 12, cuBLAS 12 e
cuDNN 9. A presença de uma GPU ou de seu driver não basta. Use `config check` para o
diagnóstico local. Nenhum binário NVIDIA é obtido pela aplicação.

Um smoke test real posterior à Etapa 3 confirmou o modelo `small` multilíngue em CPU
`int8`, com português, VAD, timestamps por palavra, métricas, cinco exportações e
persistência entre processos. Essa evidência é limitada a uma gravação curta sem gabarito
textual independente; CUDA e a validação ampla continuam pendentes.

## Contexto para contribuidores

- [AGENTS.md](AGENTS.md): regras obrigatórias para qualquer tarefa neste repositório.
- [Contrato do projeto](docs/PROJECT_CONTRACT.md): invariantes permanentes do produto.
- [Estado atual](docs/PROJECT_STATE.md): fotografia curta da versão e das capacidades atuais.
- [Roadmap](docs/ROADMAP.md): sequência autorizada das fases do projeto.
- [Decisões arquiteturais](docs/DECISIONS.md): escolhas confirmadas, motivos e consequências.
- [Problemas conhecidos](docs/KNOWN_ISSUES.md): limitações atuais sem autorização implícita para corrigi-las.
- [Arquitetura técnica](docs/FOUNDATION.md): visão viva e cumulativa do sistema atual.
- [Fundação histórica](docs/PHASE_01_FOUNDATION.md): relatório preservado da Etapa 1.
- [Biblioteca de mídia e exportadores](docs/PHASE_02_MEDIA_LIBRARY.md): relatório histórico da Etapa 2.
- [Faster Whisper e CLI](docs/PHASE_03_WHISPER_AND_CLI.md): relatório histórico da Etapa 3.
- [Validação real 3B](docs/PHASE_03B_REAL_VALIDATION.md): smoke test posterior da Etapa 3.
