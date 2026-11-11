[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [string]$Compiler = "",
    [switch]$PayloadOnly
)
$ErrorActionPreference = "Stop"
$ProgressPreference = 'SilentlyContinue'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) { $PythonExecutable = Join-Path $repositoryRoot '.venv\Scripts\python.exe' }
function Invoke-PythonChecked {
    param([string[]]$Arguments)
    & $PythonExecutable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python build failed ($LASTEXITCODE)" }
}
function Get-BuildDownload {
    param([string]$Uri, [string]$Destination)
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe --location --fail --retry 2 --connect-timeout 15 --max-time 300 --silent --show-error --output $Destination $Uri
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Uri" }
    } else {
        Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing -TimeoutSec 300
    }
}
Invoke-PythonChecked @('-c', "import sys,struct; assert sys.platform == 'win32' and sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8")
# A new directory on every build avoids stale modules and never deletes user data.
$buildRoot = Join-Path $repositoryRoot ('build\windows-' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $buildRoot 'payload'
$pythonRoot = Join-Path $payload 'python'
New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null
$archive = Join-Path $buildRoot 'python.zip'
# Official binary and published checksum, intentionally pinned for reproducibility.
# https://www.python.org/downloads/release/python-31312/
Get-BuildDownload 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip' $archive
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne '76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0') {
    throw 'Embedded Python checksum mismatch.'
}
Expand-Archive -LiteralPath $archive -DestinationPath $pythonRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $pythonRoot 'python313._pth'), "python313.zip`n.`nLib\site-packages`nimport site`n", $utf8)
$sitePackages = Join-Path $pythonRoot 'Lib\site-packages'
Invoke-PythonChecked @('-m', 'pip', 'install', '--only-binary=:all:', '--target', $sitePackages, $repositoryRoot, 'pip')
$embedded = Join-Path $pythonRoot 'python.exe'
& $embedded -B -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Packaged dependency validation failed.' }
& $embedded -B -c "import av,ctranslate2,faster_whisper,sqlite3; from importlib.resources import files; p=files('local_transcriber'); assert p.joinpath('web/index.html').is_file(); assert p.joinpath('remote_web/index.html').is_file(); from local_transcriber.desktop import main"
if ($LASTEXITCODE -ne 0) { throw 'Packaged native imports/assets failed.' }
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'LICENSE') -Destination $payload
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'packaging\windows\LEIA-ME.txt') -Destination $payload
# Native inference wheels may need the Microsoft C++ runtime on a clean PC.
$redist = Join-Path $payload 'vc_redist.x64.exe'
Get-BuildDownload 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $redist
$signature = Get-AuthenticodeSignature -LiteralPath $redist
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'Microsoft C++ redistributable signature validation failed.'
}
[IO.File]::WriteAllText((Join-Path $payload 'Abrir-LocalTranscriber.cmd'), "@echo off`r`ncd /d `"%~dp0`"`r`npython\python.exe -m local_transcriber.desktop`r`nif errorlevel 1 pause`r`n", $utf8)
$appVersion = (& $embedded -B -c "from importlib.metadata import version; print(version('local-transcriber'))").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot read package version.' }
$manifest = @{ version = $appVersion; python = '3.13.12'; head = (git -C $repositoryRoot rev-parse HEAD); dirty = [bool](git -C $repositoryRoot status --porcelain --untracked-files=no); built = [DateTime]::UtcNow.ToString('o') }
$manifest | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $payload 'build-info.json')
Get-ChildItem -LiteralPath $sitePackages -Recurse -File -Filter 'direct_url.json' | ForEach-Object {
    if (-not $_.FullName.StartsWith($payload + [IO.Path]::DirectorySeparatorChar)) { throw 'Metadata outside payload' }
    Remove-Item -LiteralPath $_.FullName
}
& $embedded -B -m pip list --format=freeze | Set-Content -Encoding UTF8 (Join-Path $payload 'dependencies.txt')
if ($LASTEXITCODE -ne 0) { throw 'Cannot record packaged dependencies.' }
$dist = Join-Path $repositoryRoot 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$portable = Join-Path $dist "LocalTranscriber-$appVersion-windows-x64.zip"
Compress-Archive -Path (Join-Path $payload '*') -DestinationPath $portable -Force
Write-Host "Portable: $portable"
if ($PayloadOnly) { Write-Output $payload; return }
if (-not $Compiler) {
    $Compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
}
if (-not (Test-Path -LiteralPath $Compiler)) { throw "Install Inno Setup 6 to compile Setup.exe, or use -PayloadOnly. Portable ZIP built: $portable" }
& $Compiler "/DPayloadDir=$payload" "/DAppVersion=$appVersion" (Join-Path $repositoryRoot 'packaging\windows\LocalTranscriber.iss')
if ($LASTEXITCODE -ne 0) { throw "Installer compiler failed ($LASTEXITCODE)" }
Get-ChildItem -LiteralPath $dist -Filter '*.exe' | Get-FileHash -Algorithm SHA256 | Format-Table -AutoSize
