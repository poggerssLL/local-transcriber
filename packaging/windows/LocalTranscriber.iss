#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
[Setup]
AppId={{FCDA092A-55BC-4BF1-8AD1-7937E48A19E4}
AppName=Local Transcriber
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\LocalTranscriber
DefaultGroupName=Local Transcriber
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist
OutputBaseFilename=LocalTranscriber-Setup-{#AppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\python\python.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "vc_redist.x64.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\vc_redist.x64.exe"; Flags: dontcopy

[Icons]
Name: "{group}\Local Transcriber"; Filename: "{app}\python\python.exe"; Parameters: "-m local_transcriber.desktop"; WorkingDir: "{app}"
Name: "{autodesktop}\Local Transcriber"; Filename: "{app}\python\python.exe"; Parameters: "-m local_transcriber.desktop"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m local_transcriber.desktop"; Description: "Abrir Local Transcriber e preparar modelos"; Flags: postinstall nowait skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Installed: Cardinal;
  MinorVersion: Cardinal;
  ResultCode: Integer;
begin
  Result := '';
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1) and
     RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Minor', MinorVersion) and (MinorVersion >= 40) then
    Exit;
  ExtractTemporaryFile('vc_redist.x64.exe');
  if not ShellExec('runas', ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := 'O Microsoft Visual C++ Runtime precisa ser instalado para continuar. Autorize sua instalacao quando o Windows solicitar.'
  else if (ResultCode <> 0) and (ResultCode <> 3010) then
    Result := 'A instalacao do Microsoft Visual C++ Runtime falhou. Codigo: ' + IntToStr(ResultCode)
  else if ResultCode = 3010 then
    NeedsRestart := True;
end;
