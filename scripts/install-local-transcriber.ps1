[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [switch]$Update
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$environmentRoot = Join-Path $repositoryRoot ".venv"
$environmentPython = Join-Path $environmentRoot "Scripts\python.exe"

function Invoke-CheckedPython {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python/pip falhou (codigo $LASTEXITCODE). Corrija o erro acima antes de continuar."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") -PathType Leaf)) {
    throw "Extraia o repositorio completo antes de executar este script."
}

# Never replace an existing environment or use an unrelated activated Python.
if (Test-Path -LiteralPath $environmentRoot) {
    if (-not $Update) {
        throw "A pasta .venv ja existe. Use -Update para reinstalar o aplicativo nela; nada foi removido."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $environmentRoot "pyvenv.cfg") -PathType Leaf) -or
        -not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
        throw "A pasta .venv nao e um ambiente valido. Preserve seus dados e escolha uma extracao nova."
    }
}
else {
    $pythonArguments = @()
    if ($PythonExecutable) {
        $selectedPython = (Get-Command $PythonExecutable -ErrorAction Stop).Source
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $selectedPython = (Get-Command py).Source
        $pythonArguments = @("-3.13")
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $selectedPython = (Get-Command python).Source
    }
    else {
        throw "Instale Python 3.13 64 bits de python.org e reabra o PowerShell. Consulte docs/INSTALLATION.md."
    }
    $checkPython = "import sys,struct,platform; assert sys.platform == 'win32' and sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64','x86_64'), 'Use Python 3.13 x64 no Windows'"
    Invoke-CheckedPython $selectedPython ($pythonArguments + @("-c", $checkPython))
    Invoke-CheckedPython $selectedPython ($pythonArguments + @("-m", "venv", $environmentRoot))
}

$checkEnvironment = "import sys,struct,pathlib,platform; assert sys.prefix != sys.base_prefix and pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(), 'Ambiente virtual incorreto'; assert sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64','x86_64'), 'Use Python 3.13 x64'"
Invoke-CheckedPython $environmentPython @("-c", $checkEnvironment, $environmentRoot)
Write-Host "Instalando o aplicativo e dependencias Python somente em .venv (internet necessaria)."
# Normal users do not need test/dev dependencies or editable installs.
Invoke-CheckedPython $environmentPython @("-m", "pip", "install", $repositoryRoot)
Invoke-CheckedPython $environmentPython @("-m", "pip", "check")
Invoke-CheckedPython $environmentPython @("-m", "local_transcriber", "--version")
Write-Host "Instalacao concluida. Nenhum modelo foi baixado e nenhum servidor foi iniciado."
Write-Host "Proximo: .\.venv\Scripts\local-transcriber.exe models download small --confirm"
Write-Host "Depois: .\scripts\start-local-transcriber.ps1"
Write-Host "Guia e diagnostico: docs/INSTALLATION.md"
