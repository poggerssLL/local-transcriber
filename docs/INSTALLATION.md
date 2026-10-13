# Instalar e usar em outro computador

O Local Transcriber roda no computador de quem o instala. Não é necessário
ter Orca, Codex, Node, conta de IA, chave de API ou placa NVIDIA.
O caminho de referência é **Windows 10/11, processador x64 e Python 3.13 64 bits**.
CPU funciona; CUDA é uma aceleração opcional. Linux, macOS e Windows ARM não
foram homologados por esta entrega. O pacote declara Python >=3.11, mas o
instalador guiado usa a versão 3.13 já validada.

## 1. Preparar o computador

1. Instale [Python 3.13 para Windows](https://www.python.org/downloads/windows/),
   escolhendo o instalador **64-bit**, com `pip`, `venv` e o launcher `py`.
   Reabra o PowerShell após instalar e confira `py -3.13 --version`.
2. Tenha internet para obter código, dependências e, separadamente, os modelos.
   Depois de instalar os modelos, a transcrição opera localmente.
3. Reserve espaço para o ambiente Python, modelos, cópias das gravações e
   exportações. O consumo varia com a duração e o modelo; CPU pode ser lenta
   em gravações longas. Comece com uma gravação curta e o modelo `small`.

Não copie a `.venv`, o banco, os modelos ou os dados pessoais de outra pessoa.
Cada computador cria seu próprio ambiente e runtime. O PyAV dos wheels já inclui
as bibliotecas de FFmpeg necessárias; o caminho padrão não exige instalar o
executável FFmpeg nem compilar código nativo.

## 2. Obter o projeto

Abra o [repositório](https://github.com/poggerssLL/local-transcriber), escolha
**Code → Download ZIP** e extraia o arquivo inteiro para uma pasta gravável.
Não execute dentro do ZIP. Abra o PowerShell na pasta extraída que contém
`pyproject.toml`, `README.md` e `scripts`.

Quem já tem Git pode usar:

```powershell
git clone https://github.com/poggerssLL/local-transcriber.git
cd local-transcriber
```

## 3. Instalar o aplicativo

Na pasta do projeto:

```powershell
.\scripts\install-local-transcriber.ps1
```

O script cria `.venv`, instala o pacote e suas dependências com pip e verifica
versão/consistência. Não exige ativar o ambiente, não instala ferramentas de
desenvolvimento, não altera configurações globais, não baixa modelos e não
inicia processos em segundo plano. Não precisa executar como administrador.
Se já existir `.venv`, ele para; `-Update` reinstala deliberadamente nesse
ambiente sem apagá-lo. Feche o servidor antes de atualizar.

Se o PowerShell bloquear scripts, você pode usar a alternativa abaixo, sem
alterar a política de execução:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\local-transcriber.exe --version
```

Se Python estiver instalado sem o launcher, informe seu executável 3.13:

```powershell
.\scripts\install-local-transcriber.ps1 -PythonExecutable "C:\caminho\Python313\python.exe"
```

## 4. Preparar o modelo de transcrição

Este é um **download explícito**, realizado somente quando você executar:

```powershell
.\.venv\Scripts\local-transcriber.exe models download small --confirm
.\.venv\Scripts\local-transcriber.exe models check small
.\.venv\Scripts\local-transcriber.exe config check
```

`small` é multilíngue e serve para português. `tiny`/`base` são alternativas
menores, com compromisso de qualidade; escolha o mesmo nome na interface.
A aplicação não baixa modelos quando você inicia uma transcrição ou o servidor.
`config check` mostra CPU/CUDA; CUDA indisponível não impede usar CPU.

## 5. Abrir e usar

```powershell
.\scripts\start-local-transcriber.ps1
```

Se scripts estiverem bloqueados, use diretamente:

```powershell
.\.venv\Scripts\local-transcriber.exe serve --host 127.0.0.1 --port 8765 --workers 1
```

Mantenha a janela aberta e acesse **http://127.0.0.1:8765** no navegador.
Crie uma matéria, importe áudio/vídeo, selecione **Transcrever**, escolha `small`
e perfil **cpu** no primeiro teste, acompanhe a fila e baixe a transcrição.
Encerre com `Ctrl+C`. O serviço é local a esse computador; ele não deve ser
exposto à internet ou configurado como `0.0.0.0`.

Os dados ficam em `%LOCALAPPDATA%\LocalTranscriber`, fora da pasta do projeto.
A importação copia a mídia para esse runtime; não compartilhe essa pasta no GitHub.
Atualizar o código não apaga esse runtime. Não exclua a pasta de dados ao remover
o aplicativo se quiser manter gravações/transcrições.

## Resumos: recurso opcional

Para transcrever/exportar, **Ollama não é necessário**. Para gerar resumos:

1. Instale [Ollama](https://ollama.com/download/windows) pelo canal oficial.
2. Execute explicitamente `ollama pull qwen2.5:3b` e confira `ollama list`.
3. Mantenha Ollama atendendo em `http://127.0.0.1:11434`. O aplicativo usa
   `qwen2.5:3b` por padrão e não instala/inicia Ollama automaticamente.
4. Gere o resumo pela interface depois de concluir a transcrição.

Resumos podem omitir, repetir ou alterar relações entre fatos. A avaliação
semântica atual exige complemento; revise o texto, os números e os timestamps
antes de utilizá-los. Transcrição também pode errar vocabulário especializado.

## Diagnóstico rápido

| Sintoma | Ação |
| --- | --- |
| `py` não encontrado ou versão 3.13 ausente | Instale Python 3.13 x64 com launcher; reabra o PowerShell ou informe `-PythonExecutable` |
| Script bloqueado | Use os comandos diretos de Python/CLI acima; não é necessário mudar política global |
| `.venv` já existe | Feche o serviço e use `-Update`; se inválida, preserve-a e faça uma extração nova |
| `No matching distribution` ou tentativa de compilar | Confira Python 3.13 x64 e acesso ao PyPI; não force instalação sem dependências |
| Erro de DLL ao importar CTranslate2 | Confira arquitetura x64 e o [Visual C++ Redistributable x64 oficial](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist); execute `config check` após corrigir |
| Modelo não instalado | Execute `models download small --confirm` e `models check small` no runtime desse usuário |
| Porta 8765 ocupada | Use `start-local-transcriber.ps1 -Port 8766` ou `serve --port 8766`; abra a mesma porta no navegador |
| Falha CUDA/cuDNN | Selecione CPU; GPU requer componentes NVIDIA compatíveis separados e não é requisito para começar |
| Ollama indisponível | Transcrição continua disponível; confira o serviço local e `ollama list` apenas para resumos |
| Arquivo não reproduz no navegador | A reprodução depende dos codecs do navegador; exportação/transcrição podem continuar disponíveis |
| Sem internet na primeira instalação | Prepare dependências/modelos previamente; ZIP sozinho não inclui Python, wheels ou modelos |

## Atualização e desenvolvimento

Com Git, feche o servidor, preserve alterações locais, obtenha a atualização e
execute `install-local-transcriber.ps1 -Update`. Não force `git reset` ou remova
dados. Com ZIP, prefira extrair a nova versão em outra pasta e instalar nela.
Não mova/reutilize `.venv` entre pastas ou máquinas.

Somente contribuidores precisam do extra `[dev]` e da suíte de testes:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest --basetemp=output/tests-dev
```

Licença: [uso pessoal e não comercial](../LICENSE), incluindo estudo individual.
Não é permitido usar o sistema em atividade comercial ou serviço remunerado sem
autorização expressa. Bibliotecas e modelos mantêm suas próprias licenças.

Referências oficiais: [instalação do Faster Whisper/PyAV e requisitos NVIDIA](https://github.com/SYSTRAN/faster-whisper#installation)
e [licenciamento de repositórios no GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).
