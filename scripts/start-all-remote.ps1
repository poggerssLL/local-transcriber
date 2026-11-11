[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$CorePort = 8765,

    [ValidateRange(1, 65535)]
    [int]$RemotePort = 8766,

    [ValidateRange(1, 65535)]
    [int]$HttpsPort = 443,

    [switch]$NoPrompt,
    [switch]$OpenBrowser = $true
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "      LOCAL TRANSCRIBER · INICIALIZADOR AUTOMATICO         " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $NoPrompt -and -not $PSBoundParameters.ContainsKey('CorePort') -and -not [Console]::IsInputRedirected) {
    Write-Host "Configuracao de Porta:" -ForegroundColor Cyan
    $promptPort = Read-Host "Informe a porta local do Local Transcriber [Pressione Enter para $CorePort]"
    if (-not [string]::IsNullOrWhiteSpace($promptPort)) {
        $parsed = 0
        if ([int]::TryParse($promptPort.Trim(), [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 65535) {
            $CorePort = $parsed
        } else {
            Write-Host "Porta '$promptPort' invalida. Mantendo $CorePort." -ForegroundColor Yellow
        }
    }
    Write-Host "Porta local configurada: $CorePort" -ForegroundColor Green
    Write-Host ""
}

# 1. Validação do executável do projeto
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $repositoryRoot ".venv\Scripts\local-transcriber.exe"

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Ambiente virtual (.venv) nao encontrado. Execute 'python -m venv .venv' e 'pip install -e .' primeiro."
}

# 2. Descoberta e Validação do Tailscale
Write-Host "[1/5] Verificando status do Tailscale..." -ForegroundColor Yellow
$tailscaleJson = $null
try {
    $tailscaleJson = tailscale status --json | ConvertFrom-Json
} catch {
    throw "Nao foi possivel executar 'tailscale status --json'. Verifique se o Tailscale esta instalado e no PATH."
}

if ($tailscaleJson.BackendState -ne "Running") {
    throw "Tailscale nao esta conectado (Estado: '$($tailscaleJson.BackendState)'). Abra o Tailscale e faca login."
}

$dnsName = $tailscaleJson.Self.DNSName.TrimEnd('.')
if ([string]::IsNullOrWhiteSpace($dnsName)) {
    throw "Nao foi possivel obter o DNSName do dispositivo no Tailscale."
}

$selfUserId = [string]$tailscaleJson.Self.UserID
$loginName = $null
if ($tailscaleJson.User -and $tailscaleJson.User.$selfUserId) {
    $loginName = $tailscaleJson.User.$selfUserId.LoginName
}
if ([string]::IsNullOrWhiteSpace($loginName) -and $tailscaleJson.CurrentTailnet) {
    $loginName = $tailscaleJson.CurrentTailnet.Name
}
if ([string]::IsNullOrWhiteSpace($loginName)) {
    throw "Nao foi possivel identificar a conta do usuario conectado no Tailscale."
}

Write-Host "      Dispositivo Tailnet : $dnsName" -ForegroundColor Green
Write-Host "      Usuario Conectado   : $loginName" -ForegroundColor Green

# 3. Consulta e garantia de matérias
Write-Host "[2/5] Mapeando materias cadastradas..." -ForegroundColor Yellow
$subjectsRaw = & $entryPoint subjects list
$subjectIds = @()

if ($subjectsRaw) {
    foreach ($line in $subjectsRaw) {
        $parts = $line -split "`t"
        if ($parts.Count -ge 1 -and [Guid]::TryParse($parts[0].Trim(), [ref][Guid]::Empty)) {
            $subjectIds += $parts[0].Trim()
        }
    }
}

if ($subjectIds.Count -eq 0) {
    Write-Host "      Nenhuma materia encontrada. Criando materia inicial 'Geral'..." -ForegroundColor Cyan
    & $entryPoint subjects add "Geral"
    $subjectsRaw = & $entryPoint subjects list
    foreach ($line in $subjectsRaw) {
        $parts = $line -split "`t"
        if ($parts.Count -ge 1 -and [Guid]::TryParse($parts[0].Trim(), [ref][Guid]::Empty)) {
            $subjectIds += $parts[0].Trim()
        }
    }
}

Write-Host "      Materias autorizadas: $($subjectIds.Count) encontradas." -ForegroundColor Green

# 4. Geração do gateway.json (UTF-8 estrito sem BOM)
Write-Host "[3/5] Gravando configuracao segura do gateway..." -ForegroundColor Yellow
$remoteDir = Join-Path $env:LOCALAPPDATA "LocalTranscriber\remote"
if (-not (Test-Path -LiteralPath $remoteDir -PathType Container)) {
    [System.IO.Directory]::CreateDirectory($remoteDir) | Out-Null
}
$gatewayConfigPath = Join-Path $remoteDir "gateway.json"

$configObject = [ordered]@{
    enabled            = $true
    allowed_identities = @($loginName)
    allowed_hosts      = @($dnsName)
    allowed_origins    = @("https://$dnsName")
    allowed_subjects   = @($subjectIds)
    model_name         = "small"
    profile            = "auto"
    language           = "pt"
}

$jsonText = $configObject | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($gatewayConfigPath, $jsonText, $utf8NoBom)
Write-Host "      gateway.json gerado com sucesso (UTF-8 sem BOM)." -ForegroundColor Green

# 5. Inicialização do Core API (se não estiver rodando)
Write-Host "[4/5] Verificando Core API (porta $CorePort)..." -ForegroundColor Yellow
$coreManagedByMe = $false
$coreProcess = $null
$coreHealthUrl = "http://127.0.0.1:$CorePort/api/health"

$coreIsAlive = $false
try {
    $response = Invoke-RestMethod -Uri $coreHealthUrl -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($response.status -eq "ok" -or $response) { $coreIsAlive = $true }
} catch {}

if ($coreIsAlive) {
    Write-Host "      Core API ja esta rodando em http://127.0.0.1:$CorePort." -ForegroundColor Green
} else {
    # Se a porta desejada nao e 8765, verificar se ha outro Core ativo na porta padrao 8765 segurando a trava
    if ($CorePort -ne 8765) {
        $otherCoreAlive = $false
        try {
            $testOld = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($testOld.status -eq "ok") { $otherCoreAlive = $true }
        } catch {}

        if ($otherCoreAlive) {
            $oldConn = Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -ne $oldConn) {
                Write-Host "      Detectado Core anterior ativo na porta 8765 (PID $($oldConn.OwningProcess))." -ForegroundColor Yellow
                Write-Host "      Encerrando instancia anterior para liberar a nova porta $CorePort..." -ForegroundColor Yellow
                Stop-Process -Id $oldConn.OwningProcess -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 800
            }
        }
    }

    $listener = Get-NetTCPConnection -State Listen -LocalPort $CorePort -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $listener) {
        throw "A porta $CorePort ja esta em uso pelo processo com PID $($listener.OwningProcess). Encerre o processo conflitante ou verifique o servico."
    }

    $logDir = Join-Path $env:LOCALAPPDATA "LocalTranscriber\logs"
    if (-not (Test-Path -LiteralPath $logDir)) {
        [System.IO.Directory]::CreateDirectory($logDir) | Out-Null
    }
    $coreErrLog = Join-Path $logDir "core-startup.err.log"
    $coreOutLog = Join-Path $logDir "core-startup.out.log"

    Write-Host "      Iniciando Core API em segundo plano..." -ForegroundColor Cyan
    $coreProcess = Start-Process -FilePath $entryPoint `
        -ArgumentList @("serve", "--host", "127.0.0.1", "--port", "$CorePort", "--workers", "1") `
        -RedirectStandardError $coreErrLog `
        -RedirectStandardOutput $coreOutLog `
        -WindowStyle Hidden -PassThru
    $coreManagedByMe = $true

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if ($coreProcess.HasExited) {
            $errDetail = ""
            if (Test-Path -LiteralPath $coreErrLog) {
                $errDetail = (Get-Content -Path $coreErrLog -Tail 5 -ErrorAction SilentlyContinue | Out-String).Trim()
            }
            if ($errDetail -match "another API worker is already active") {
                throw "Existe outro processo do Local Transcriber ativo segurando o banco de dados. Encerre o processo anterior ou use a mesma porta."
            }
            throw "Processo do Core API encerrou inesperadamente (codigo de saida: $($coreProcess.ExitCode)). Detalhe: $errDetail"
        }
        try {
            $resp = Invoke-RestMethod -Uri $coreHealthUrl -Method Get -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($resp.status -eq "ok" -or $resp) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) {
        throw "Core API falhou ao inicializar na porta $CorePort dentro de 15 segundos."
    }
    Write-Host "      Core API inicializado e saudavel." -ForegroundColor Green
}

# 6. Inicialização da Sessão Remota
Write-Host "[5/5] Subindo Sessao Remota Privada..." -ForegroundColor Yellow

$gwListener = Get-NetTCPConnection -State Listen -LocalPort $RemotePort -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $gwListener) {
    Write-Host "      Liberando porta remota $RemotePort (encerrando sessao anterior PID $($gwListener.OwningProcess))..." -ForegroundColor Yellow
    Stop-Process -Id $gwListener.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 600
}

if ($OpenBrowser) {
    try {
        Start-Process "http://127.0.0.1:$CorePort/"
        Write-Host "      Modo Local aberto no seu navegador: http://127.0.0.1:$CorePort/" -ForegroundColor Cyan
    } catch {}
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "      LOCAL TRANSCRIBER (LOCAL + REMOTO) ATIVO!             " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Modo Local (no seu computador):" -ForegroundColor White
Write-Host "  >>  http://127.0.0.1:$CorePort/" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Modo Remoto (no Safari do seu iPad):" -ForegroundColor White
Write-Host "  >>  https://$dnsName/" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Conta autorizada : $loginName" -ForegroundColor Gray
Write-Host "  Para encerrar ambos os servicos com seguranca, pressione Ctrl+C" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

$remoteArgs = @("remote-session", "start", "--port", "$RemotePort", "--https-port", "$HttpsPort")
if ($CorePort -ne 8765) {
    $remoteArgs += "--no-check-core"
}

try {
    & $entryPoint @remoteArgs
} finally {
    Write-Host ""
    Write-Host "Encerrando sessao remota e liberando recursos..." -ForegroundColor Yellow
    try {
        & $entryPoint remote-session stop
    } catch {}

    if ($coreManagedByMe -and $coreProcess -and (-not $coreProcess.HasExited)) {
        Write-Host "Parando Core API iniciado por este script..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $coreProcess.Id -Force -ErrorAction SilentlyContinue
        } catch {}
    }
    Write-Host "Sessao encerrada com seguranca." -ForegroundColor Green
}
