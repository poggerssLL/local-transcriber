[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8766,

    [ValidateRange(1, 65535)]
    [int]$HttpsPort = 443,

    [switch]$NoCheckCore
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $repositoryRoot ".venv\Scripts\local-transcriber.exe"

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Ambiente virtual não encontrado. Crie .venv e instale o projeto antes de iniciar a sessão remota."
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -ne $listener) {
    throw "A porta local $Port já está em uso. Encerre o serviço conflitante ou informe outra porta com -Port."
}

Write-Host "Iniciando Sessão Privada Temporária do Local Transcriber..."
Write-Host "Use Ctrl+C nesta janela ou execute 'local-transcriber remote-session stop' para encerrar."

$argsList = @("remote-session", "start", "--port", $Port, "--https-port", $HttpsPort)
if ($NoCheckCore) {
    $argsList += "--no-check-core"
}

& $entryPoint @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
