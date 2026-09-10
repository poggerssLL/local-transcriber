# Local Transcriber

Aplicação local para catalogar gravações e executar transcrição com Faster Whisper.
A versão atual inclui importação segura e inspeção de mídia, pesquisa SQLite FTS5,
transcrição local síncrona, fila persistente com worker local, API FastAPI restrita ao
localhost, interface web local, eventos SSE e exportadores TXT, Markdown, SRT, WebVTT e JSON.

Versão atual: `0.6.1`, com schema SQLite v4.

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
local-transcriber jobs enqueue ID --model small --profile auto --language auto
local-transcriber jobs list
local-transcriber jobs show JOB_ID
local-transcriber jobs cancel JOB_ID
local-transcriber jobs retry JOB_ID
local-transcriber worker run --once
local-transcriber worker run
local-transcriber transcripts list
local-transcriber transcripts show ID
local-transcriber export ID --format srt
local-transcriber serve
```

`models download` é a única operação que pode obter um modelo e exige `--confirm`.
Uma transcrição comum abre exclusivamente o diretório já instalado com
`local_files_only=True`; se o modelo estiver ausente, o comando falha sem acessar a rede.

`transcribe` continua síncrono. `jobs enqueue` apenas persiste o trabalho, e `worker run`
processa a fila localmente com concorrência padrão 1. Jobs mantêm progresso e eventos no
SQLite, aceitam cancelamento e retry e recuperam leases expiradas. A recuperação pode
reiniciar a inferência desde o começo; a execução é `at least once`, enquanto a publicação
final permanece idempotente e limitada a uma transcrição por job.

O heartbeat distingue erros SQLite transitórios de perda de posse: tenta renovar de
forma limitada enquanto existe margem segura e sinaliza o worker quando a lease não pode
mais ser garantida. Somente o proprietário da lease válida pode persistir progresso ou
publicar. Após uma expiração pode haver breve sobreposição de computação até o worker
obsoleto alcançar um ponto cooperativo, mas a publicação transacional impede dois
resultados finais para o mesmo job.

Quando a fila está vazia, o worker faz apenas uma pré-consulta SQLite de leitura. Havendo
job pendente ou lease vencida, ele entra em `BEGIN IMMEDIATE` e repete a validação antes do
compare-and-set, preservando a reivindicação atômica sem disputar lock de escrita em cada
polling. `SQLITE_BUSY` e `SQLITE_LOCKED` durante a reivindicação recebem espera curta e
retry limitado; falhas permanentes encerram o controlador com erro registrado.

## API local

O comando abaixo inicia a API e o worker local sequencial:

```powershell
local-transcriber serve
```

O endereço padrão é `http://127.0.0.1:8765`. A interface abre nesse endereço e a
especificação OpenAPI JSON fica disponível localmente em
`http://127.0.0.1:8765/api/openapi.json`. Não há Swagger UI, ReDoc nem visualizador HTML
dos contratos: isso evita dependências de CDN e mantém a operação completamente offline.
O comando recusa bind público e múltiplos workers. Também existe
um lock por diretório de runtime para impedir dois consumidores da mesma fila SQLite.

Principais contratos:

- `GET /api/health`, `/api/version` e `/api/capabilities`;
- `GET|POST /api/subjects`;
- `GET|POST /api/recordings` e `GET|DELETE /api/recordings/{id}`;
- `GET /api/search?q=...`;
- `GET /api/models` e `/api/runtime`;
- `GET|POST /api/jobs`, detalhes, cancelamento e retry;
- `GET /api/transcripts`, detalhes, segmentos e palavras;
- criação, listagem e download de exportações;
- `GET /api/recordings/{id}/media`, com suporte a Range;
- `GET /api/jobs/{id}/events`, com SSE, heartbeat e `Last-Event-ID`.

O SSE consulta apenas sequências posteriores ao último ID entregue, em lotes limitados.
Backlogs são drenados sem aguardar entre lotes; o intervalo de polling só é aplicado após
uma consulta incremental vazia. O schema permanece v4 e usa o índice existente por job e
sequência.

Uploads são progressivos, limitados e validados por nome, Content-Type, contêiner e
decodificação. A API nunca aceita um caminho de arquivo do cliente e não devolve caminhos
físicos. `Host` e `Origin` local são validados, não há CORS wildcard e erros internos não
retornam stack trace. Toda transcrição criada pela API passa pela fila; desconectar o SSE
não cancela o job.

## Interface web

Inicie o serviço e abra `http://127.0.0.1:8765` no navegador:

```powershell
local-transcriber serve
```

A interface funciona sem instalação de Node, etapa de build, CDN ou conexão com a
internet. Ela permite:

- consultar serviço, worker, perfil recomendado, modelo e jobs recentes;
- criar matérias, importar e pesquisar gravações e filtrar a biblioteca;
- revisar configurações e confirmar uma transcrição antes de enviá-la para a fila;
- acompanhar fase, progresso e tempo por SSE, com recuperação após recarga e reconexão;
- cancelar ou repetir jobs, reproduzir a mídia e navegar por segmentos temporais;
- ler texto e métricas e baixar TXT, Markdown, SRT, WebVTT e JSON;
- verificar modelos instalados e copiar a orientação explícita da CLI quando faltarem.

Os dados da API são inseridos no DOM como texto, sem interpretação como HTML. O layout
oferece navegação por teclado, foco visível, regiões de anúncio e adaptação para notebooks
e telas menores. O download de modelos não é iniciado pela interface.

Modelos ausentes são informados com a ação necessária. O download continua disponível
somente pela CLI explícita:

```powershell
local-transcriber models download small --confirm
```

Perfis de execução:

- `cpu`: CPU com `int8`;
- `cuda`: NVIDIA com `int8_float16`, sem fallback, após a sondagem do runtime;
- `auto`: usa CUDA somente quando o dispositivo, o tipo de computação e as DLLs exigidas
  estão disponíveis; caso contrário usa CPU `int8` e informa o motivo.

No Windows, o runtime atual do Faster Whisper/CTranslate2 exige CUDA 12, cuBLAS 12 e
cuDNN 9. A presença de uma GPU ou de seu driver não basta. Use `config check` para o
diagnóstico local. Nenhum binário NVIDIA é obtido pela aplicação.

Duas validações reais posteriores à Etapa 3 confirmaram o modelo `small` multilíngue em
CPU `int8`, com português, VAD, timestamps por palavra, métricas, cinco exportações e
persistência entre processos. Os RTFs observados foram 1,612 e 0,4778. Essas evidências
continuam limitadas a duas gravações curtas sem gabarito textual independente; desempenho
em cargas longas, CUDA e a validação ampla permanecem pendentes para a Etapa 7.

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
- [Validação real 3C](docs/PHASE_03C_SECOND_REAL_VALIDATION.md): segunda execução real da Etapa 3.
- [Fila persistente](docs/PHASE_04_PERSISTENT_QUEUE.md): relatório histórico da Etapa 4.
- [Confiabilidade de lease 4B](docs/PHASE_04B_LEASE_RELIABILITY.md): correção
  complementar do heartbeat e da perda de posse.
- [API local e SSE](docs/PHASE_05_LOCAL_API_AND_SSE.md): contratos HTTP, segurança,
  streaming, eventos persistentes e lifecycle do worker.
- [Correção 5B](docs/PHASE_05B_OFFLINE_DOCS_AND_INCREMENTAL_SSE.md): OpenAPI JSON offline
  e leitura incremental dos eventos SSE.
- [Interface web](docs/PHASE_06_WEB_INTERFACE.md): aplicação vanilla, acessibilidade,
  fluxos locais e validação visual da Etapa 6.
- [Confiabilidade SQLite 5C](docs/PHASE_05C_SQLITE_CONTENTION_RELIABILITY.md): prevenção
  de contenção no polling ocioso e retry limitado da reivindicação.
