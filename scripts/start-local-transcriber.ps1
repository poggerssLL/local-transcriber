[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    [switch]$OpenBrowser,
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

if (-not $NoPrompt -and -not $PSBoundParameters.ContainsKey('Port') -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Write-Host "Configuracao de Porta:" -ForegroundColor Cyan
    $promptPort = Read-Host "Informe a porta local do Local Transcriber [Pressione Enter para $Port]"
    if (-not [string]::IsNullOrWhiteSpace($promptPort)) {
        $parsed = 0
        if ([int]::TryParse($promptPort.Trim(), [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 65535) {
            $Port = $parsed
        } else {
            Write-Host "Porta '$promptPort' invalida. Mantendo $Port." -ForegroundColor Yellow
        }
    }
    Write-Host "Usando porta local: $Port" -ForegroundColor Green
    Write-Host ""
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $repositoryRoot ".venv\Scripts\local-transcriber.exe"

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Ambiente virtual não encontrado. Crie .venv e instale o projeto antes de iniciar o serviço."
}

$healthUrl = "http://127.0.0.1:$Port/api/health"
$coreIsAlive = $false
try {
    $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1 -ErrorAction SilentlyContinue
    if ($response.status -eq "ok" -or $response) { $coreIsAlive = $true }
} catch {}

if ($coreIsAlive) {
    Write-Host "Local Transcriber já está em execução em http://127.0.0.1:$Port." -ForegroundColor Green
    if ($OpenBrowser) {
        Write-Host "Abrindo no navegador..." -ForegroundColor Cyan
        Start-Process "http://127.0.0.1:$Port"
    }
    return
}

if ($Port -ne 8765) {
    $otherAlive = $false
    try {
        $testOld = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1 -ErrorAction SilentlyContinue
        if ($testOld.status -eq "ok") { $otherAlive = $true }
    } catch {}
    if ($otherAlive) {
        $oldConn = Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $oldConn) {
            Write-Host "Detectado Local Transcriber ativo na porta 8765 (PID $($oldConn.OwningProcess)). Encerrando para liberar a porta $Port..." -ForegroundColor Yellow
            Stop-Process -Id $oldConn.OwningProcess -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 600
        }
    }
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -ne $listener) {
    throw "A porta local $Port já está em uso por outro aplicativo. Escolha outra com -Port, por exemplo: -Port 8766."
}

Write-Host "Iniciando Local Transcriber em http://127.0.0.1:$Port..." -ForegroundColor Cyan
Write-Host "Use Ctrl+C nesta janela para encerrar o servidor e o worker local." -ForegroundColor Yellow

if ($OpenBrowser) {
    $browserScript = "Start-Sleep -Milliseconds 800; for (`$i=0; `$i -lt 30; `$i++) { try { `$r = Invoke-RestMethod 'http://127.0.0.1:$Port/api/health' -TimeoutSec 1; if (`$r) { Start-Process 'http://127.0.0.1:$Port'; break } } catch { Start-Sleep -Milliseconds 400 } }"
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-Command", $browserScript) -WindowStyle Hidden
}

& $entryPoint serve --host 127.0.0.1 --port $Port --workers 1
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
