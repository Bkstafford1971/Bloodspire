[Setup]
AppName=Bloodspire Arena
AppVersion=1.0
; Sets the installation directory to C:\BloodspireArena
DefaultDirName=C:\BloodspireArena
DefaultGroupName=Bloodspire Arena
; Sets the icon for the Add/Remove Programs entry
UninstallDisplayIcon={app}\BloodspireIcon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
OutputDir=userdocs:Inno Setup Output
; Sets the icon for the actual Setup.exe installer file
SetupIconFile=C:\BPClone_Claude\assets\BloodspireIcon.ico

[Files]
; Places the HTML client into the new C:\BloodspireArena directory
Source: "C:\BPClone_Claude\bloodspire_client.html"; DestDir: "{app}"; Flags: ignoreversion
; Copies the icon file to the installation folder for the shortcut to use
Source: "C:\BPClone_Claude\assets\BloodspireIcon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Creates the desktop shortcut called "Bloodspire" using the copied icon
Name: "{userdesktop}\Bloodspire"; Filename: "{app}\bloodspire_client.html"; IconFilename: "{app}\BloodspireIcon.ico"

[Run]
; Opens the Game Client after installation
Filename: "{app}\bloodspire_client.html"; \
    Description: "Launch Bloodspire Arena"; \
    Flags: postinstall shellexec