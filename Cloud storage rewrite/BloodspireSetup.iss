[Setup]
AppName=Bloodspire
AppVersion=1.2
DefaultDirName=C:\Bloodspire
PrivilegesRequired=admin
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Bloodspire_Installer
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
; SetupIconFile requires an .ico/.exe/.dll icon source. Remove or replace if you have an .ico file.
;SetupIconFile=Bloodspire.png

[Files]
; Include all root files and directories for the game, excluding the Tailscale installer batch file since Tailscale is installed automatically
Source: "*.*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "INSTALL_TAILSCALE.bat"

[Icons]
Name: "{commondesktop}\Bloodspire"; Filename: "{app}\START_GAME.bat"; WorkingDir: "{app}"

[Messages]
WelcomeLabel1=Welcome to the Bloodspire Installer
WelcomeLabel2=This will install Bloodspire to C:\Bloodspire and automatically install Tailscale and portable Python.


[Code]
const
  LeagueConfigContent =
    '{' + #13#10 +
    '  "league_server_url": "http://100.114.138.61:8766"' + #13#10 +
    '}' + #13#10;
  TailscaleUrl = 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe';
  PythonZipUrl = 'https://www.python.org/ftp/python/3.11.7/python-3.11.7-embed-amd64.zip';
  InstallLogFile = '{tmp}\BloodspireInstaller.log';

var
  TailscaleSuccess: Boolean;
  PythonSuccess: Boolean;

// Import Windows API functions for downloading
function URLDownloadToFile(
  pCaller: Integer;
  szURL: String;
  szFileName: String;
  dwReserved: Integer;
  lpfnCB: Integer
): Integer;
external 'URLDownloadToFileA@urlmon.dll stdcall';

function ShellExecute(
  hwnd: Integer;
  lpOperation: String;
  lpFile: String;
  lpParameters: String;
  lpDirectory: String;
  nShowCmd: Integer
): Integer;
external 'ShellExecuteA@shell32.dll stdcall';

function LogMessage(const Text: String): Boolean;
begin
  Result := SaveStringToFile(ExpandConstant(InstallLogFile), Text + #13#10, True);
end;

procedure InitializeWizard();
begin
  WizardForm.ProgressGauge.Max := 100;
  WizardForm.ProgressGauge.Position := 0;
  WizardForm.StatusLabel.Caption := '';
end;

procedure UpdateStatus(const Msg: String; Position: Integer);
begin
  LogMessage('Status: ' + Msg);
  if WizardForm.ProgressGauge.Visible then
  begin
    WizardForm.StatusLabel.Caption := Msg;
    if Position >= 0 then
      WizardForm.ProgressGauge.Position := Position;
    WizardForm.StatusLabel.Update;
    WizardForm.ProgressGauge.Update;
  end;
end;

function DownloadFile(URL, FileName: String): Boolean;
var
  ResultCode: Integer;
begin
  LogMessage('Downloading: ' + URL);
  ResultCode := URLDownloadToFile(0, URL, FileName, 0, 0);
  Result := ResultCode = 0;
  if not Result then
  begin
    LogMessage('URLDownloadToFile failed with code ' + IntToStr(ResultCode) + '. Falling back to PowerShell.');
    if Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri ''' + URL + ''' -OutFile ''' + FileName + '''; exit $LASTEXITCODE } catch { exit 1 }"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := ResultCode = 0
    else
      Result := False;
  end;
  LogMessage('Download result: ' + IntToStr(ResultCode) + ' -> ' + FileName);
end;

function AddToSystemPath(NewPath: String): Boolean;
var
  CurrentPath: String;
  Haystack: String;
  Needle: String;
begin
  Result := False;
  if not RegQueryStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', CurrentPath) then
  begin
    LogMessage('Failed to read system PATH');
    Exit;
  end;

  Haystack := ';' + Lowercase(CurrentPath) + ';';
  Needle := ';' + Lowercase(NewPath) + ';';
  if Pos(Needle, Haystack) > 0 then
  begin
    LogMessage('PATH already contains: ' + NewPath);
    Result := True;
    Exit;
  end;

  if (Length(CurrentPath) > 0) and (CurrentPath[Length(CurrentPath)] <> ';') then
    CurrentPath := CurrentPath + ';';
  CurrentPath := CurrentPath + NewPath;

  if RegWriteExpandStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', CurrentPath) then
  begin
    LogMessage('Added to system PATH: ' + NewPath);
    Result := True;
  end
  else
    LogMessage('Failed to write system PATH');
end;

function RunInstaller(FileName, Params: String; const Name: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  LogMessage('Running installer: ' + FileName + ' ' + Params);
  if not FileExists(FileName) then
  begin
    LogMessage('Installer missing: ' + FileName);
    Exit;
  end;
  if Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    LogMessage(Name + ' exit code: ' + IntToStr(ResultCode));
    Result := ResultCode = 0;
  end
  else
    LogMessage(Name + ' exec failed');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: string;
  TailscaleInstallerPath: string;
  PythonArchivePath: string;
  ResultCode: Integer;
  FinalMessage: String;
begin
  if CurStep = ssInstall then
  begin
    UpdateStatus('Copying files to game directory...', 10);
    Exit;
  end;

  if CurStep = ssPostInstall then
  begin
    LogMessage('Post-install step started');
    UpdateStatus('Creating league config...', 20);

    // Create league config file
    ConfigPath := ExpandConstant('{app}\league_config.json');
    if not FileExists(ConfigPath) then
    begin
      SaveStringToFile(ConfigPath, LeagueConfigContent, False);
      LogMessage('Created league_config.json');
    end;

    // Install portable Python
    PythonArchivePath := ExpandConstant('{tmp}\python-portable.zip');
    PythonSuccess := False;
    UpdateStatus('Downloading portable Python...', 30);
    if DownloadFile(PythonZipUrl, PythonArchivePath) then
    begin
      UpdateStatus('Extracting portable Python...', 50);
      if not DirExists(ExpandConstant('{app}\PortablePython')) then
        ForceDirectories(ExpandConstant('{app}\PortablePython'));

      ResultCode := -1;
      if FileExists('C:\Program Files\7-Zip\7z.exe') then
      begin
        if not Exec('C:\Program Files\7-Zip\7z.exe', 'x "' + PythonArchivePath + '" -o"' + ExpandConstant('{app}\PortablePython') + '" -y', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
          ResultCode := -1;
      end
      else if FileExists('C:\Program Files (x86)\7-Zip\7z.exe') then
      begin
        if not Exec('C:\Program Files (x86)\7-Zip\7z.exe', 'x "' + PythonArchivePath + '" -o"' + ExpandConstant('{app}\PortablePython') + '" -y', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
          ResultCode := -1;
      end
      else
      begin
        if not Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path ''' + PythonArchivePath + ''' -DestinationPath ''' + ExpandConstant('{app}\PortablePython') + ''' -Force"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
          ResultCode := -1;
      end;

      LogMessage('Python extraction result code: ' + IntToStr(ResultCode));
      if ResultCode = 0 then
      begin
        SaveStringToFile(ExpandConstant('{app}\PortablePython\python.bat'), '@"%~dp0python.exe" %*', False);
        LogMessage('Portable Python extracted successfully');
        PythonSuccess := True;
        UpdateStatus('Adding Python to system PATH...', 60);
        AddToSystemPath(ExpandConstant('{app}\PortablePython'));
      end;
      DeleteFile(PythonArchivePath);
    end;

    if not PythonSuccess then
    begin
      UpdateStatus('Portable Python installation failed', 60);
      MsgBox('Portable Python installation failed. See log: ' + ExpandConstant(InstallLogFile), mbError, MB_OK);
    end;

    // Install Tailscale
    TailscaleInstallerPath := ExpandConstant('{tmp}\tailscale-setup.exe');
    TailscaleSuccess := False;
    UpdateStatus('Downloading Tailscale...', 65);
    if DownloadFile(TailscaleUrl, TailscaleInstallerPath) then
    begin
      UpdateStatus('Installing Tailscale...', 80);
      if RunInstaller(TailscaleInstallerPath, '/quiet /norestart', 'Tailscale') then
      begin
        LogMessage('Tailscale installed successfully');
        TailscaleSuccess := True;
      end;
      DeleteFile(TailscaleInstallerPath);
    end;

    if not TailscaleSuccess then
    begin
      UpdateStatus('Tailscale installation failed', 90);
      MsgBox('Tailscale installation failed. See log: ' + ExpandConstant(InstallLogFile), mbError, MB_OK);
    end;

    if TailscaleSuccess and PythonSuccess then
      FinalMessage := 'Installation complete! Bloodspire, portable Python, and Tailscale were installed successfully.'
    else if TailscaleSuccess then
      FinalMessage := 'Installation complete, but portable Python failed. See log: ' + ExpandConstant(InstallLogFile)
    else if PythonSuccess then
      FinalMessage := 'Installation complete, but Tailscale failed. See log: ' + ExpandConstant(InstallLogFile)
    else
      FinalMessage := 'Installation complete, but both portable Python and Tailscale failed. See log: ' + ExpandConstant(InstallLogFile);

    UpdateStatus(FinalMessage, 100);
    MsgBox(FinalMessage, mbInformation, MB_OK);
  end;
end;
