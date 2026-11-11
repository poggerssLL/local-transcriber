[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Installer)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $repositoryRoot ('output\maintenance-' + [guid]::NewGuid().ToString('N'))
$installRoot = Join-Path $testRoot 'app'
$runtimeRoot = Join-Path $testRoot 'runtime'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{FCDA092A-55BC-4BF1-8AD1-7937E48A19E4}_is1'
if (Test-Path $uninstallKey) { throw 'An installation already exists. It will not be touched.' }
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$sentinel = Join-Path $runtimeRoot 'preserve.txt'
[IO.File]::WriteAllText($sentinel, 'synthetic user data must survive')

function Invoke-TestSetup {
    param([string]$Action)
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
        ('/DIR="' + $installRoot + '"'),
        ('/LOG="' + (Join-Path $testRoot "$Action.log") + '"'))
    if ($Action -ne 'install') { $arguments += "/MAINTENANCE=$Action" }
    $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($Action -in @('install', 'update') -and $process.ExitCode -ne 0) {
        throw "Setup $Action failed ($($process.ExitCode))"
    }
    return $process.ExitCode
}

try {
    Invoke-TestSetup 'install' | Out-Null
    $uninstaller = Join-Path $installRoot 'unins000.exe'
    if (-not (Test-Path $uninstallKey) -or -not (Test-Path -LiteralPath $uninstaller)) {
        throw 'Fresh install did not register its uninstaller'
    }
    Invoke-TestSetup 'cancel' | Out-Null
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw 'Cancel removed the installation' }
    Invoke-TestSetup 'update' | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $installRoot 'python\python.exe'))) {
        throw 'Update removed the program'
    }
    Invoke-TestSetup 'uninstall' | Out-Null
    if (Test-Path $uninstallKey) { throw 'Maintenance did not remove the registration' }
    if (Test-Path -LiteralPath (Join-Path $installRoot 'python\python.exe')) {
        throw 'Maintenance did not remove the program'
    }
    $log = Get-Content -Raw -LiteralPath (Join-Path $testRoot 'uninstall.log')
    if ($log -notmatch 'Maintenance: uninstall completed') { throw 'Uninstall branch did not complete' }
    if ((Get-Content -Raw -LiteralPath $sentinel) -ne 'synthetic user data must survive') {
        throw 'Synthetic user data changed'
    }
    Write-Output 'PASS: install, cancel, update, uninstall through Setup, synthetic data preserved'
    Write-Output "Evidence: $testRoot"
} finally {
    # Only this test-owned installation may be cleaned up, never a pre-existing app.
    $ownedUninstaller = Join-Path $installRoot 'unins000.exe'
    if (Test-Path -LiteralPath $ownedUninstaller) {
        Start-Process -FilePath $ownedUninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -WindowStyle Hidden -Wait | Out-Null
    }
}
