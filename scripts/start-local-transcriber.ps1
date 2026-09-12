[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $repositoryRoot ".venv\Scripts\local-transcriber.exe"

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Ambiente virtual não encontrado. Crie .venv e instale o projeto antes de iniciar o serviço."
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -ne $listener) {
    throw "A porta local $Port já está em uso. Escolha outra com -Port, por exemplo: -Port 8766."
}

Write-Host "Iniciando Local Transcriber em http://127.0.0.1:$Port"
Write-Host "Use Ctrl+C nesta janela para encerrar o servidor e o worker local."

& $entryPoint serve --host 127.0.0.1 --port $Port --workers 1
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
