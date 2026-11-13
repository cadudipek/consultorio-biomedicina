; Instalador do Consultório (Inno Setup 6)
#define AppName "Consultório"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0E5C3A-2F4D-4C5B-9D1E-7A3C8F2B1E40}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Carlos Eduardo Dias Peres Pequeno
DefaultDirName={autopf}\Consultorio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=Consultorio-Setup-{#AppVersion}
SetupIconFile=..\assets\icone.ico
UninstallDisplayIcon={app}\Consultorio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; Flags: checkedonce
Name: "demoicon"; Description: "Criar também o atalho de DEMONSTRAÇÃO (dados fictícios)"; Flags: unchecked

[Files]
Source: "..\dist\Consultorio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Consultorio.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Consultorio.exe"; Tasks: desktopicon
Name: "{autodesktop}\{#AppName} (demonstração)"; Filename: "{app}\Consultorio.exe"; Parameters: "--demo"; Tasks: demoicon

[Run]
Filename: "{app}\Consultorio.exe"; Description: "Abrir o {#AppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Os dados dos pacientes ficam em %LOCALAPPDATA%\Consultorio e NÃO são apagados ao desinstalar.
Type: filesandordirs; Name: "{app}"
