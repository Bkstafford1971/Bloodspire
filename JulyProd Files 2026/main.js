console.log('=== MAIN.JS LOADING ===');

if (require('electron-squirrel-startup')) {
  console.log('Squirrel startup detected, exiting');
  process.exit(0);
}

console.log('Loading modules...');
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const pathLib = require('path');
const fs = require('fs-extra');
const https = require('https');
const { autoUpdater } = require('electron-updater');

// File-based logging for debugging (works in packaged app)
let logFile = null;
function logToFile(message) {
  try {
    if (!logFile) {
      // Try userData first, fall back to temp folder
      try {
        const userDataPath = app.getPath('userData');
        logFile = pathLib.join(userDataPath, 'update-check.log');
        fs.ensureDirSync(pathLib.dirname(logFile));
      } catch (e) {
        // Fallback to temp
        const tempPath = process.env.TEMP || process.env.TMP || 'C:\\Temp';
        logFile = pathLib.join(tempPath, 'bloodspire-update-check.log');
        fs.ensureDirSync(pathLib.dirname(logFile));
      }
    }
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}] ${message}\n`;
    fs.appendFileSync(logFile, logMessage, { encoding: 'utf8' });
  } catch (err) {
    console.error('Failed to write log:', err);
  }
  console.log(message); // Also log to console
}

// Disable hardware acceleration to resolve UI focus and rendering issues
app.disableHardwareAcceleration();

// Configure electron-updater
autoUpdater.checkForUpdatesAndNotify = false; // Disable default notification; we'll handle it
autoUpdater.autoDownload = false; // We'll download on demand after user agrees
autoUpdater.allowDowngrade = false;
autoUpdater.logger = console; // Log to console for debugging

// Set GitHub provider explicitly
autoUpdater.setFeedURL({
  provider: 'github',
  owner: 'Bkstafford1971',
  repo: 'Bloodspire'
});

// Use GitHub API v3 releases instead of relying on latest.yml
autoUpdater.channel = 'latest';


// Global variable to store the base directory path
let baseDir = null;
let mainWindow;

const configPath = pathLib.join(app.getPath('userData'), 'config.json');
const { version: currentVersion } = require('../package.json');

// ============================================================
// UPDATE CHECK (electron-updater)
// ============================================================

let updateAvailable = false;
let updateInfo = null;

function checkForUpdates() {
  return new Promise((resolve) => {
    const debugInfo = { currentVersion, status: 'checking' };
    console.log('🔄 Starting update check for version:', currentVersion);

    autoUpdater.checkForUpdates()
      .then((result) => {
        debugInfo.status = 'completed';
        debugInfo.resultExists = !!result;
        debugInfo.hasUpdateInfo = !!(result && result.updateInfo);

        console.log('✓ Update check completed:', debugInfo);

        if (result && result.updateInfo) {
          const newVersion = result.updateInfo.version;
          debugInfo.remoteVersion = newVersion;
          console.log('Remote version from GitHub:', newVersion);

          if (newVersion !== currentVersion) {
            updateAvailable = true;
            updateInfo = result.updateInfo;
            debugInfo.updateFound = true;
            debugInfo.fullUpdateInfo = result.updateInfo;
            console.log('✓ Update available:', newVersion);
            console.log('Full updateInfo structure:', result.updateInfo);

            if (mainWindow && !mainWindow.isDestroyed()) {
              showUpdatePrompt(newVersion);
            }
          } else {
            debugInfo.updateFound = false;
            console.log('✓ App is up to date');
          }
        } else {
          debugInfo.noUpdateInfo = true;
          console.warn('⚠ No updateInfo in result');
        }
        resolve(debugInfo);
      })
      .catch((err) => {
        debugInfo.status = 'failed';
        debugInfo.error = err.message;
        console.error('✗ Update check failed:', err);
        resolve(debugInfo);
      });
  });
}

function showUpdatePrompt(newVersion) {
  dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Update Available',
    message: `Bloodspire ${newVersion} is available`,
    detail: 'A new version is ready to install. Update now or exit the application.',
    buttons: ['Update Now', 'Exit'],
    defaultId: 0,
    cancelId: 1
  }).then((result) => {
    if (result.response === 0) {
      // User chose "Update Now"
      downloadAndInstallUpdate();
    } else {
      // User chose "Exit"
      app.quit();
    }
  });
}

function downloadAndInstallUpdate() {
  if (!updateAvailable || !updateInfo) {
    console.error('No update available');
    return;
  }

  console.log('Starting update download for Squirrel...');

  // For Squirrel/NSIS on Windows, download the .exe and run it directly
  const https = require('https');
  const { exec } = require('child_process');
  const tempDir = process.env.TEMP || 'C:\\Temp';
  const installerPath = pathLib.join(tempDir, 'bloodspire-update.exe');

  // Construct download URL from updateInfo (GitHub releases format)
  console.log('updateInfo:', updateInfo);

  let filename = updateInfo.path; // e.g., "bloodspire-2.8.5 Setup.exe"
  const tag = updateInfo.tag;       // e.g., "v2.8.5"

  if (!filename || !tag) {
    dialog.showErrorBox('Update Failed', 'Missing filename or tag in updateInfo');
    return;
  }

  // GitHub uses dots instead of spaces in filenames
  filename = filename.replace(/ /g, '.');

  // Construct GitHub release download URL
  const downloadUrl = `https://github.com/Bkstafford1971/Bloodspire/releases/download/${tag}/${encodeURIComponent(filename)}`;
  console.log('Download URL:', downloadUrl);

  // Show status dialog
  dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Downloading Update',
    message: 'Downloading Bloodspire ' + updateInfo.version + '...',
    detail: 'Please wait. The application will install and restart automatically.',
    noLink: true
  });

  // Download the installer with redirect support
  const file = fs.createWriteStream(installerPath);
  const { https: httpsModule } = require('follow-redirects');

  console.log('Starting download from:', downloadUrl);

  // Add headers to tell the server we want a direct download (bypass browser security)
  const headers = {
    'User-Agent': 'Electron-Updater',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache'
  };

  httpsModule.get(downloadUrl, { headers }, (response) => {
    console.log('Response status:', response.statusCode);
    console.log('Response headers:', response.headers);

    const totalSize = parseInt(response.headers['content-length'], 10);
    let downloadedSize = 0;

    console.log('Total file size:', totalSize);

    response.on('data', (chunk) => {
      downloadedSize += chunk.length;
      const percent = Math.round((downloadedSize / totalSize) * 100);
      console.log(`Download progress: ${percent}% (${downloadedSize}/${totalSize} bytes)`);
    });

    response.pipe(file);
    file.on('finish', () => {
      file.close();
      console.log('Installer downloaded to:', installerPath);
      console.log('File size downloaded:', downloadedSize, 'bytes');

      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update:installing');
      }

      // Verify file was downloaded
      console.log('Download complete. File path:', installerPath);
      console.log('File exists:', fs.existsSync(installerPath));

      if (!fs.existsSync(installerPath)) {
        dialog.showErrorBox('Download Error', 'Installer file was not found at:\n' + installerPath);
        return;
      }

      // Remove Windows "Mark of the Web" (Zone.Identifier) that blocks downloaded files
      const { execSync } = require('child_process');
      try {
        console.log('Removing Zone.Identifier (unblocking file)...');
        // PowerShell command to remove the zone identifier
        execSync(`powershell -Command "Unblock-File -Path '${installerPath}'"`, {
          stdio: 'pipe',
          windowsHide: true
        });
        console.log('File unblocked successfully');
      } catch (err) {
        console.warn('Warning: Could not unblock file (may not be needed):', err.message);
      }

      // Verify file size is correct (should be > 100MB for installer)
      const stat = fs.statSync(installerPath);
      console.log('Downloaded file size:', stat.size, 'bytes');

      function handleBlockedDownload() {
        dialog.showMessageBox(mainWindow, {
          type: 'warning',
          title: 'Download May Be Blocked',
          message: 'Your security software may have blocked the download.',
          detail: 'The file size is incorrect. This usually means antivirus or a firewall blocked it.\n\nYou can:\n1. Retry the download\n2. Manually trust the file (if it was partially downloaded)',
          buttons: ['Retry Download', 'Manually Trust File', 'Cancel'],
          defaultId: 0
        }).then((result) => {
          if (result.response === 0) {
            // Retry - delete old file and restart download
            console.log('User chose to retry download');
            fs.unlink(installerPath, () => {
              downloadAndInstallUpdate();
            });
          } else if (result.response === 1) {
            // Manually trust - open folder and show continue button
            console.log('User chose to manually trust');
            showManualTrustDialog();
          }
          // If 2 (Cancel), do nothing
        });
      }

      function showManualTrustDialog() {
        // Open the temp folder so user can manually trust the file
        shell.openPath(pathLib.dirname(installerPath)).catch((err) => {
          console.error('Failed to open folder:', err);
        });

        dialog.showMessageBox(mainWindow, {
          type: 'info',
          title: 'Manual Trust Required',
          message: 'The file has been opened in File Explorer.',
          detail: 'If you see the file:\n\n1. Right-click on it\n2. Select "Properties"\n3. Check the box "Unblock" at the bottom\n4. Click "Apply" then "OK"\n\nOr, your antivirus may show a trust prompt - click "Allow" or "Trust".\n\nOnce done, click "Continue" to proceed with installation.',
          buttons: ['Continue', 'Cancel'],
          defaultId: 0
        }).then((result) => {
          if (result.response === 0) {
            // User clicked Continue - check if file is now valid
            try {
              const newStat = fs.statSync(installerPath);
              if (newStat.size >= 100000000) {
                console.log('File now valid, proceeding with installation');
                proceedWithInstaller();
              } else {
                dialog.showErrorBox('File Still Invalid', 'The file size is still incorrect. Please try again later.');
              }
            } catch (err) {
              dialog.showErrorBox('Error', 'Could not verify file: ' + err.message);
            }
          }
        });
      }

      if (stat.size < 100000000) {
        // Check if file is actually HTML (error page) instead of executable
        let isErrorPage = false;
        try {
          const head = fs.readFileSync(installerPath, { encoding: 'utf8', flag: 'r' }).substring(0, 500);
          if (head.includes('<html') || head.includes('<!DOCTYPE') || head.includes('github')) {
            isErrorPage = true;
          }
        } catch (e) {
          console.log('Could not read file head, may be binary');
        }

        if (isErrorPage) {
          dialog.showErrorBox('Download Failed', 'Downloaded file appears to be an error page.\n\nThis usually means:\n- Network/firewall is blocking the download\n- Corporate proxy intercepting the connection\n\nTry:\n1. Disabling antivirus temporarily\n2. Checking firewall settings\n3. Trying again later');
        } else {
          handleBlockedDownload();
        }
        return;
      }

      // Show success dialog and instruct user to run installer
      showInstallDialog();
    });

    function proceedWithInstaller() {
      showInstallDialog();
    }

    function showInstallDialog() {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: 'Update Ready',
        message: 'Update download complete!',
        detail: 'The installer is ready. Click OK to install and restart Bloodspire.',
        buttons: ['Install Now', 'Cancel']
      }).then((result) => {
        if (result.response === 0) {
          // User clicked "Install Now"
          console.log('Starting installation...');
          logToFile('USER CLICKED: Install Now');

          // Get the app executable path (changes with Squirrel versioning)
          const appExePath = process.execPath; // Current app path
          const appDir = pathLib.dirname(appExePath);
          console.log('App path:', appExePath);
          console.log('App dir:', appDir);
          logToFile('App path: ' + appExePath);
          logToFile('App dir: ' + appDir);

          // Get the restart script path (in resources folder for packaged app)
          const restartScript = pathLib.join(appDir, 'resources', 'restart-after-update.bat');
          console.log('Restart script path:', restartScript);
          logToFile('Restart script path: ' + restartScript);

          // Verify script exists
          if (!fs.existsSync(restartScript)) {
            console.error('Restart script not found at:', restartScript);
            logToFile('ERROR: Restart script not found at: ' + restartScript);
            // Don't show error dialog - window is about to close
            return;
          }
          logToFile('Restart script verified - file exists');

          // Hide main window (don't close it - that triggers app quit)
          if (mainWindow && !mainWindow.isDestroyed()) {
            console.log('Hiding main window...');
            logToFile('Hiding main window');
            mainWindow.hide();
          }

          // Launch installer after window is hidden
          setTimeout(() => {
            try {
              console.log('Launching installer directly...');
              logToFile('Launching installer: ' + installerPath);

              const { spawn } = require('child_process');

              // Run installer with /S flag for silent mode
              // Use shell: true to properly handle spaces in paths
              const installer = spawn(installerPath, ['/S'], {
                detached: true,
                stdio: 'ignore',
                windowsHide: true,
                shell: true
              });

              installer.unref();

              console.log('Installer spawned');
              logToFile('Installer spawned successfully');

              // Exit app after a brief delay to ensure installer process started
              setTimeout(() => {
                console.log('App exiting to allow update...');
                logToFile('App exiting now - installer will run and restart app');
                process.exit(0);
              }, 1000);

            } catch (err) {
              console.error('Failed to launch installer:', err);
              logToFile('ERROR launching installer: ' + err.message);
              // App will close anyway
            }
          }, 500);
        }
      });
    }
  }).on('error', (err) => {
    fs.unlink(installerPath, () => {}); // Delete partial download
    console.error('Download error:', err);
    dialog.showErrorBox('Update Failed', 'Failed to download update:\n\n' + err.message);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update:failed');
    }
  });
}

// Helper to resolve absolute path using the saved base directory
async function resolvePath(filePath, throwOnMissing = true) {
  if (pathLib.isAbsolute(filePath)) return filePath;
  
  if (!baseDir && configPath && await fs.pathExists(configPath)) {
    const config = await fs.readJson(configPath);
    baseDir = config.baseDir;
  }

  if (!baseDir) {
    if (throwOnMissing) throw new Error("Please select your Bloodspire folder first.");
    return null;
  }
  return pathLib.join(baseDir, filePath);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 800,
    webPreferences: {
      preload: MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY,
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  // Re-assert webContents focus whenever the window gains OS focus.
  // This is critical: when the user restores the window or returns from a dialog,
  // we must re-establish WM_SETFOCUS routing so keypresses reach the webContents.
  // After a dialog closes or window is restored, the focus state can be stale.
  mainWindow.on('focus', () => {
    setTimeout(() => {
      if (!mainWindow.isDestroyed()) {
        mainWindow.webContents.focus();
        // Notify renderer that focus was reclaimed at OS level
        mainWindow.webContents.send('window:focus-reclaimed');
      }
    }, 50);
  });

  // Also re-assert focus when the window shows (can happen after hide/show)
  mainWindow.on('show', () => {
    setTimeout(() => {
      if (!mainWindow.isDestroyed()) {
        mainWindow.focus();
        mainWindow.webContents.focus();
      }
    }, 100);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.focus();
        mainWindow.webContents.focus();
      }
    }, 300);
  });

  if (typeof MAIN_WINDOW_WEBPACK_ENTRY !== 'undefined') {
    mainWindow.loadURL(MAIN_WINDOW_WEBPACK_ENTRY);
  } else {
    // Fallback if not running via Electron Forge Webpack dev server
    mainWindow.loadURL(MAIN_WINDOW_WEBPACK_ENTRY);
  }
// === OPEN DEVTOOLS AUTOMATICALLY ===
// mainWindow.webContents.openDevTools();

  // Optional: Open it on the right side (detached)
  // mainWindow.webContents.openDevTools({ mode: 'detach' });

}

// Renderer requests keyboard-focus reclaim from the main process.
//
// Why blur+focus instead of just webContents.focus():
// On Windows, webContents.focus() only sets Blink's internal focus flag — it
// does NOT make the OS route WM_KEYDOWN to our window. That routing is set up
// by WM_SETFOCUS, which Windows only sends when focus TRANSITIONS to our window.
// If the window already appears focused (e.g. after returning from a dialog or
// navigating views), mainWindow.focus() → SetForegroundWindow() is a no-op.
// Calling blur() first forces WM_KILLFOCUS → then focus() forces WM_SETFOCUS,
// which is exactly what minimize/maximize does and why that workaround works.
// The returned Promise resolves only after the cycle is done so the renderer
// can safely call element.focus() knowing OS keyboard routing is established.
ipcMain.handle('window:focus', () => {
  return new Promise(resolve => {
    if (!mainWindow || mainWindow.isDestroyed()) { resolve(); return; }
    mainWindow.blur();
    setTimeout(() => {
      if (!mainWindow || mainWindow.isDestroyed()) { resolve(); return; }
      mainWindow.focus();
      setTimeout(resolve, 100); // let WM_SETFOCUS propagate before renderer focuses element
    }, 50);
  });
});

app.whenReady().then(async () => {
  logToFile('=== APP STARTED ===');
  logToFile('Version: ' + currentVersion);

  try {
    if (await fs.pathExists(configPath)) {
      const config = await fs.readJson(configPath);
      if (config.baseDir) {
        baseDir = config.baseDir;
      }
    }
  } catch (err) {
    console.log('No saved config found');
  }

  createWindow();

  // Check for updates after window is created but before it finishes loading
  // Give the window a moment to be ready
  setTimeout(async () => {
    logToFile('500ms timeout reached, checking for updates...');
    if (mainWindow && !mainWindow.isDestroyed()) {
      logToFile('mainWindow exists, calling checkForUpdates()');
      try {
        const result = await checkForUpdates();
        logToFile('checkForUpdates completed with result:', JSON.stringify(result));
      } catch (err) {
        logToFile('checkForUpdates error:', err.message);
      }
    } else {
      logToFile('⚠ mainWindow is destroyed or null');
    }
  }, 500);
});

// ============================================================
// IPC HANDLERS - All handlers defined once
// ============================================================

// Set base directory (called from renderer after folder selection)
ipcMain.handle('file:setBaseDir', async (event, dirPath) => {
  if (dirPath) {
    baseDir = dirPath;
    // Save the folder path for next time
    try {
      await fs.writeJson(configPath, { baseDir: baseDir });
      console.log('Saved folder path to config:', baseDir);
    } catch (err) {
      console.error('Failed to save config:', err);
    }
    
    return { success: true };
  }
  return { success: false, error: 'No path provided' };
});

// Folder selection dialog
ipcMain.handle('dialog:openDirectory', async () => {
  // Pass mainWindow so the dialog is modal — Electron will return focus to the
  // window when the native dialog closes rather than leaving it focus-less.
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory']
  });

  // Native dialogs can steal keyboard focus from the webContents. Reclaim it.
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.focus();
    mainWindow.webContents.focus();
  }

  if (!result.canceled && result.filePaths.length > 0) {
    baseDir = result.filePaths[0];
    try {
      const config = await fs.readJson(configPath).catch(() => ({}));
      await fs.writeJson(configPath, { ...config, baseDir: baseDir });
      console.log('Base directory set to:', baseDir);
    } catch (err) {
      console.error('Failed to save config:', err);
    }
    return baseDir;
  }
  return null;
});

// Get list of saved folders from config
ipcMain.handle('config:getSavedFolders', async () => {
  try {
    if (await fs.pathExists(configPath)) {
      const config = await fs.readJson(configPath);
      return config.savedFolders || [];
    }
  } catch (err) {
    console.error('Failed to read saved folders:', err);
  }
  return [];
});

// Add folder to saved list
ipcMain.handle('config:addSavedFolder', async (event, { path: folderPath, name }) => {
  try {
    // Validate folder exists
    if (!await fs.pathExists(folderPath)) {
      return { success: false, error: 'Folder does not exist' };
    }

    const config = await fs.readJson(configPath).catch(() => ({ baseDir, savedFolders: [] }));
    if (!config.savedFolders) config.savedFolders = [];

    // Check if already in list
    if (config.savedFolders.some(f => f.path === folderPath)) {
      return { success: false, error: 'Folder already in saved list' };
    }

    // Add to list
    config.savedFolders.push({ path: folderPath, name: name || folderPath });
    await fs.writeJson(configPath, config);
    console.log('Added saved folder:', folderPath);
    return { success: true, folders: config.savedFolders };
  } catch (err) {
    console.error('Failed to add saved folder:', err);
    return { success: false, error: err.message };
  }
});

// Remove folder from saved list
ipcMain.handle('config:removeSavedFolder', async (event, folderPath) => {
  try {
    const config = await fs.readJson(configPath).catch(() => ({ baseDir, savedFolders: [] }));
    if (!config.savedFolders) config.savedFolders = [];

    config.savedFolders = config.savedFolders.filter(f => f.path !== folderPath);
    await fs.writeJson(configPath, config);
    console.log('Removed saved folder:', folderPath);
    return { success: true, folders: config.savedFolders };
  } catch (err) {
    console.error('Failed to remove saved folder:', err);
    return { success: false, error: err.message };
  }
});

// Switch to a saved folder
ipcMain.handle('config:switchToFolder', async (event, folderPath) => {
  try {
    // Validate folder exists
    if (!await fs.pathExists(folderPath)) {
      return { success: false, error: 'Folder does not exist' };
    }

    baseDir = folderPath;
    const config = await fs.readJson(configPath).catch(() => ({ savedFolders: [] }));
    await fs.writeJson(configPath, { ...config, baseDir: folderPath });
    console.log('Switched to folder:', folderPath);
    return { success: true };
  } catch (err) {
    console.error('Failed to switch folder:', err);
    return { success: false, error: err.message };
  }
});

// Write JSON file
ipcMain.handle('file:writeJson', async (event, { path: filePath, data }) => {
  try {
    const absolutePath = await resolvePath(filePath);

    const dir = pathLib.dirname(absolutePath);
    await fs.ensureDir(dir);
    await fs.writeJson(absolutePath, data, { spaces: 2 });
    
    console.log(`Written: ${absolutePath}`);
    return { success: true };
  } catch (err) {
    console.error("Write Error:", err);
    return { success: false, error: err.message };
  }
});

// Read JSON file
ipcMain.handle('file:readJson', async (event, filePath) => {
  try {
    const absolutePath = await resolvePath(filePath, false);
    if (!absolutePath) return { success: false, error: "No base directory" };

    if (!(await fs.pathExists(absolutePath))) {
      return { success: false, error: "File not found" };
    }
    
    const data = await fs.readJson(absolutePath);
    return { success: true, data };
  } catch (err) {
    console.error("Read Error:", err);
    return { success: false, error: err.message };
  }
});

// Delete file
ipcMain.handle('file:deleteFile', async (event, filePath) => {
  try {
    const absolutePath = await resolvePath(filePath, false);
    if (!absolutePath) return { success: false, error: "No base directory" };
    
    if (await fs.pathExists(absolutePath)) {
      await fs.remove(absolutePath);
    }
    return { success: true };
  } catch (err) {
    console.error("Delete Error:", err);
    return { success: false, error: err.message };
  }
});

// List directory
ipcMain.handle('file:listDir', async (event, dirPath) => {
  try {
    const absolutePath = await resolvePath(dirPath, false);
    if (!absolutePath) return { success: false, error: "No base directory" };

    await fs.ensureDir(absolutePath);
    const files = await fs.readdir(absolutePath);
    return { success: true, files };
  } catch (err) {
    console.error("ListDir Error:", err);
    return { success: false, error: err.message };
  }
});

// Check if file exists
ipcMain.handle('file:exists', async (event, filePath) => {
  try {
    const absolutePath = await resolvePath(filePath, false);
    if (!absolutePath) return false;
    return await fs.pathExists(absolutePath);
  } catch (err) {
    return false;
  }
});

// Read text file
ipcMain.handle('file:readText', async (event, filePath) => {
  try {
    const absolutePath = await resolvePath(filePath, false);
    if (!absolutePath) return { success: false, error: "No base directory" };

    if (!(await fs.pathExists(absolutePath))) {
      return { success: false, error: "File not found" };
    }
    
    const text = await fs.readFile(absolutePath, 'utf8');
    return { success: true, text };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

// Write text file
ipcMain.handle('file:writeText', async (event, { path: filePath, text }) => {
  try {
    const absolutePath = await resolvePath(filePath);
    
    const dir = pathLib.dirname(absolutePath);
    await fs.ensureDir(dir);
    await fs.writeFile(absolutePath, text, 'utf8');
    return { success: true };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

// Ensure directory exists
ipcMain.handle('file:ensureDir', async (event, dirPath) => {
  try {
    const absolutePath = await resolvePath(dirPath, false);
    if (!absolutePath) return { success: false, error: "No base directory" };
    await fs.ensureDir(absolutePath);
    return { success: true };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

// ============================================================
// UPDATE EVENT HANDLERS
// ============================================================

ipcMain.handle('test:ping', async () => {
  console.log('test:ping handler called');
  return { success: true, message: 'PONG' };
});

ipcMain.handle('update:check', async () => {
  console.log('update:check handler called');
  return await checkForUpdates();
});

ipcMain.handle('update:download', async () => {
  console.log('update:download handler called');
  if (updateAvailable) {
    downloadAndInstallUpdate();
    return { success: true };
  }
  return { success: false, error: 'No update available' };
});

ipcMain.handle('data:getManagerRecord', async (event, managerName) => {
  const debugLog = (msg) => {
    console.log(msg);
    try {
      const logPath = pathLib.join(app.getPath('userData'), 'manager-record-debug.log');
      fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${msg}\n`, 'utf8');
    } catch (e) {
      // Silent fail if can't write to file
    }
  };

  debugLog('data:getManagerRecord handler called for: ' + managerName);

  try {
    // Ensure baseDir is loaded from config if not already set
    if (!baseDir && configPath && await fs.pathExists(configPath)) {
      const config = await fs.readJson(configPath);
      baseDir = config.baseDir;
    }

    if (!baseDir) {
      return { success: false, error: 'Please select your Bloodspire folder first.' };
    }

    // Check for teams folder in both possible locations
    let teamsDir = pathLib.join(baseDir, 'teams');
    if (!fs.existsSync(teamsDir)) {
      teamsDir = pathLib.join(baseDir, 'saves', 'teams');
    }

    if (!fs.existsSync(teamsDir)) {
      return { success: false, error: `Teams directory not found. Checked: ${pathLib.join(baseDir, 'teams')} and ${pathLib.join(baseDir, 'saves', 'teams')}` };
    }

    // Find league results directory (check multiple locations)
    let leagueResultsDir = pathLib.join(baseDir, 'saves', 'league');
    if (!fs.existsSync(leagueResultsDir)) {
      leagueResultsDir = pathLib.join(baseDir, 'league');
    }
    if (!fs.existsSync(leagueResultsDir)) {
      leagueResultsDir = pathLib.join(baseDir, 'results');
    }

    const managerRecords = {};
    const raceRecords = {};
    const raceVsRace = {};
    const weaponRecords = {};
    const weaponByRace = {};
    const weaponByRaceByWarrior = {};
    const allSlainByRace = {};
    const processedFightIds = new Set();
    const leagueTeamIds = new Set(); // Dynamically discovered from league results
    let totalWins = 0, totalLosses = 0, totalKills = 0, totalDeaths = 0;
    let maxTurnFromResults = 0;

    // Read all team files
    const files = fs.readdirSync(teamsDir).filter(f => f.endsWith('.json') && !f.endsWith('.checksum'));

    // STEP 0: Discover which team IDs are in the league (by scanning league results first)
    if (fs.existsSync(leagueResultsDir)) {
      const items = fs.readdirSync(leagueResultsDir);
      const turnDirs = items.filter(f => {
        const fullPath = pathLib.join(leagueResultsDir, f);
        return f.startsWith('turn_') && fs.statSync(fullPath).isDirectory();
      });
      const resultFiles = items.filter(f => (f.startsWith('team_') || f.startsWith('result_')) && f.endsWith('.json'));

      // Process old format: league/turn_X/result_Y.json
      for (const turnDir of turnDirs) {
        const turnPath = pathLib.join(leagueResultsDir, turnDir);
        const nestedFiles = fs.readdirSync(turnPath).filter(f => f.startsWith('result_') && f.endsWith('.json'));
        for (const resultFile of nestedFiles) {
          try {
            const resultData = JSON.parse(fs.readFileSync(pathLib.join(turnPath, resultFile), 'utf8'));
            if (resultData.manager_name === managerName && resultData.team_id) {
              leagueTeamIds.add(resultData.team_id);
            }
          } catch (err) {
            // Silently skip files that can't be parsed
          }
        }
      }

      // Process new format: results/team_Z_turn_X.json (flat structure)
      for (const resultFile of resultFiles) {
        try {
          const resultData = JSON.parse(fs.readFileSync(pathLib.join(leagueResultsDir, resultFile), 'utf8'));
          if (resultData.manager_name === managerName && resultData.team_id) {
            leagueTeamIds.add(resultData.team_id);
          }
        } catch (err) {
          // Silently skip files that can't be parsed
        }
      }
    }
    debugLog(`Discovered league team IDs for ${managerName}: [${Array.from(leagueTeamIds).join(',')}]`);

    // STEP 1: Process league results first to populate processedFightIds and get accurate weapon/race stats
    if (fs.existsSync(leagueResultsDir)) {
      const items = fs.readdirSync(leagueResultsDir);
      const turnDirs = items.filter(f => {
        const fullPath = pathLib.join(leagueResultsDir, f);
        return f.startsWith('turn_') && fs.statSync(fullPath).isDirectory();
      });
      const resultFiles = items.filter(f => (f.startsWith('team_') || f.startsWith('result_')) && f.endsWith('.json'));

      // Process old format: league/turn_X/result_Y.json
      for (const turnDir of turnDirs) {
        const turnPath = pathLib.join(leagueResultsDir, turnDir);
        const nestedFiles = fs.readdirSync(turnPath).filter(f => f.startsWith('result_') && f.endsWith('.json'));

        for (const resultFile of nestedFiles) {
          try {
            const resultPath = pathLib.join(turnPath, resultFile);
            const resultData = JSON.parse(fs.readFileSync(resultPath, 'utf8'));

            if (resultData.manager_name !== managerName) continue;
            // Process all teams for this manager - team IDs are dynamically assigned per manager

            const warriorMap = {};
            if (resultData.team && resultData.team.warriors) {
              for (const warrior of resultData.team.warriors) {
                warriorMap[warrior.name] = {
                  race: warrior.race,
                  primary_weapon: warrior.primary_weapon || 'Open Hand'
                };
              }
            }

            for (const bout of (resultData.bouts || [])) {
              const warriorData = warriorMap[bout.warrior_name];
              if (!warriorData) continue;

              // Track this fight to avoid duplicates
              if (bout.fight_id) {
                processedFightIds.add(bout.fight_id);
              }

              // Track max turn from results
              maxTurnFromResults = Math.max(maxTurnFromResults, resultData.turn || 0);

              const opponent = bout.opponent_manager;
              const race = warriorData.race || 'Unknown';
              const opponentRace = bout.opponent_race || 'Unknown';
              const weapon = warriorData.primary_weapon;

              if (!managerRecords[opponent]) {
                managerRecords[opponent] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }
              if (!raceRecords[race]) {
                raceRecords[race] = { wins: 0, losses: 0, kills: 0, deaths: 0, slain: 0 };
              }
              if (!weaponRecords[weapon]) {
                weaponRecords[weapon] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              // Track race vs race matchups
              if (!raceVsRace[race]) {
                raceVsRace[race] = {};
              }
              if (!raceVsRace[race][opponentRace]) {
                raceVsRace[race][opponentRace] = { wins: 0, losses: 0, kills: 0, slain: 0 };
              }
              if (!weaponByRace[weapon]) {
                weaponByRace[weapon] = {};
              }
              if (!weaponByRace[weapon][race]) {
                weaponByRace[weapon][race] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              // Track warrior+weapon+race performance
              const warriorName = bout.warrior_name;
              if (!weaponByRaceByWarrior[weapon]) {
                weaponByRaceByWarrior[weapon] = {};
              }
              if (!weaponByRaceByWarrior[weapon][race]) {
                weaponByRaceByWarrior[weapon][race] = {};
              }
              if (!weaponByRaceByWarrior[weapon][race][warriorName]) {
                weaponByRaceByWarrior[weapon][race][warriorName] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              const resultUpper = bout.result.toUpperCase();
              if (resultUpper === 'WIN') {
                managerRecords[opponent].wins++;
                raceRecords[race].wins++;
                raceVsRace[race][opponentRace].wins++;
                weaponRecords[weapon].wins++;
                weaponByRace[weapon][race].wins++;
                weaponByRaceByWarrior[weapon][race][warriorName].wins++;
                totalWins++;
              } else if (resultUpper === 'LOSS') {
                managerRecords[opponent].losses++;
                raceRecords[race].losses++;
                raceVsRace[race][opponentRace].losses++;
                weaponRecords[weapon].losses++;
                weaponByRace[weapon][race].losses++;
                weaponByRaceByWarrior[weapon][race][warriorName].losses++;
                totalLosses++;
              }

              if (bout.opponent_slain) {
                managerRecords[opponent].kills++;
                raceRecords[race].kills++;
                raceVsRace[race][opponentRace].kills++;
                weaponRecords[weapon].kills++;
                weaponByRace[weapon][race].kills++;
                weaponByRaceByWarrior[weapon][race][warriorName].kills++;
                totalKills++;
              }

              if (bout.warrior_slain) {
                managerRecords[opponent].deaths++;
                raceRecords[race].deaths++;
                raceVsRace[race][opponentRace].slain++;
                weaponRecords[weapon].deaths++;
                weaponByRace[weapon][race].deaths++;
                weaponByRaceByWarrior[weapon][race][warriorName].deaths++;
                totalDeaths++;
              }
            }
          } catch (err) {
            // Silently skip files that can't be parsed
          }
        }
      }

      // Process new format: results/team_Z_turn_X.json (flat structure)
      for (const resultFile of resultFiles) {
        try {
          const resultPath = pathLib.join(leagueResultsDir, resultFile);
          const resultData = JSON.parse(fs.readFileSync(resultPath, 'utf8'));

          if (resultData.manager_name !== managerName) continue;
          // Process all teams for this manager

          const warriorMap = {};
          if (resultData.team && resultData.team.warriors) {
            for (const warrior of resultData.team.warriors) {
              warriorMap[warrior.name] = {
                race: warrior.race,
                primary_weapon: warrior.primary_weapon || 'Open Hand'
              };
            }
          }

          for (const bout of (resultData.bouts || [])) {
            const warriorData = warriorMap[bout.warrior_name];
            if (!warriorData) continue;

            // Track this fight to avoid duplicates
            if (bout.fight_id) {
              processedFightIds.add(bout.fight_id);
            }

            // Track max turn from results
            maxTurnFromResults = Math.max(maxTurnFromResults, resultData.turn || 0);

            const opponent = bout.opponent_manager;
            const race = warriorData.race || 'Unknown';
            const opponentRace = bout.opponent_race || 'Unknown';
            const weapon = warriorData.primary_weapon;

            if (!managerRecords[opponent]) {
              managerRecords[opponent] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }
            if (!raceRecords[race]) {
              raceRecords[race] = { wins: 0, losses: 0, kills: 0, deaths: 0, slain: 0 };
            }
            if (!weaponRecords[weapon]) {
              weaponRecords[weapon] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            // Track race vs race matchups
            if (!raceVsRace[race]) {
              raceVsRace[race] = {};
            }
            if (!raceVsRace[race][opponentRace]) {
              raceVsRace[race][opponentRace] = { wins: 0, losses: 0, kills: 0, slain: 0 };
            }
            if (!weaponByRace[weapon]) {
              weaponByRace[weapon] = {};
            }
            if (!weaponByRace[weapon][race]) {
              weaponByRace[weapon][race] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            // Track warrior+weapon+race performance
            const warriorName = bout.warrior_name;
            if (!weaponByRaceByWarrior[weapon]) {
              weaponByRaceByWarrior[weapon] = {};
            }
            if (!weaponByRaceByWarrior[weapon][race]) {
              weaponByRaceByWarrior[weapon][race] = {};
            }
            if (!weaponByRaceByWarrior[weapon][race][warriorName]) {
              weaponByRaceByWarrior[weapon][race][warriorName] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            const resultUpper = bout.result.toUpperCase();
            if (resultUpper === 'WIN') {
              managerRecords[opponent].wins++;
              raceRecords[race].wins++;
              raceVsRace[race][opponentRace].wins++;
              weaponRecords[weapon].wins++;
              weaponByRace[weapon][race].wins++;
              weaponByRaceByWarrior[weapon][race][warriorName].wins++;
              totalWins++;
            } else if (resultUpper === 'LOSS') {
              managerRecords[opponent].losses++;
              raceRecords[race].losses++;
              raceVsRace[race][opponentRace].losses++;
              weaponRecords[weapon].losses++;
              weaponByRace[weapon][race].losses++;
              weaponByRaceByWarrior[weapon][race][warriorName].losses++;
              totalLosses++;
            }

            if (bout.opponent_slain) {
              managerRecords[opponent].kills++;
              raceRecords[race].kills++;
              raceVsRace[race][opponentRace].kills++;
              weaponRecords[weapon].kills++;
              weaponByRace[weapon][race].kills++;
              weaponByRaceByWarrior[weapon][race][warriorName].kills++;
              totalKills++;
            }

            if (bout.warrior_slain) {
              managerRecords[opponent].deaths++;
              raceRecords[race].deaths++;
              raceVsRace[race][opponentRace].slain++;
              weaponRecords[weapon].deaths++;
              weaponByRace[weapon][race].deaths++;
              weaponByRaceByWarrior[weapon][race][warriorName].deaths++;
              totalDeaths++;
            }
          }
        } catch (err) {
          // Silently skip files that can't be parsed
        }
      }
    }

    // STEP 2: Process team files' archived warrior counts and then augment with non-duplicated team fights
    debugLog(`Processing ${files.length} team files for manager: ${managerName}`);
    debugLog(`Reading from teams directory: ${teamsDir}`);

    for (const file of files) {
      try {
        const teamPath = pathLib.join(teamsDir, file);
        const teamData = JSON.parse(fs.readFileSync(teamPath, 'utf8'));

        debugLog(`Read team file ${file}: manager_name="${teamData.manager_name}", team_id=${teamData.team_id}`);

        if (teamData.manager_name !== managerName) {
          debugLog(`  Skipping: manager_name doesn't match (looking for "${managerName}", got "${teamData.manager_name}")`);
          continue;
        }

        debugLog(`Found team file for ${managerName}: ${file} (team_id: ${teamData.team_id})`);

        // Only process teams that are in the league (dynamically discovered from league results)
        // If we found league results, only count teams in the league
        // If we didn't find league results, count all teams for this manager (fallback)
        if (leagueTeamIds.size > 0) {
          if (!leagueTeamIds.has(teamData.team_id)) {
            debugLog(`  Skipping team ${teamData.team_id} - not in discovered league teams: [${Array.from(leagueTeamIds)}]`);
            continue;
          }
        } else {
          debugLog(`  WARNING: No league team IDs discovered, processing ALL teams for ${managerName}`);
        }

        // Accumulate archived/dead warriors by race across all teams
        if (teamData.archived_warriors) {
          for (const w of teamData.archived_warriors) {
            if (w && w.name && w.race) {
              allSlainByRace[w.race] = (allSlainByRace[w.race] || 0) + 1;
            }
          }
        }

        // Also count fallen warriors from current turn
        if (teamData.fallen_warriors) {
          for (const w of teamData.fallen_warriors) {
            if (w && w.name && w.race && w.is_dead) {
              allSlainByRace[w.race] = (allSlainByRace[w.race] || 0) + 1;
            }
          }
        }

        // Helper function to process fight history
        const processFightHistory = (warrior) => {
          if (!warrior || !warrior.fight_history) {
            if (warrior && warrior.name) {
              console.log(`Warrior ${warrior.name} has no fight_history`);
            }
            return;
          }

          console.log(`Warrior ${warrior.name} has ${warrior.fight_history.length} fights`);

          const warriorRace = warrior.race || 'Unknown';
          if (!raceRecords[warriorRace]) {
            raceRecords[warriorRace] = { wins: 0, losses: 0, kills: 0, deaths: 0, slain: 0 };
          }

          for (const fight of warrior.fight_history) {
            // Skip if we already processed this fight from league results
            if (fight.fight_id && processedFightIds.has(fight.fight_id)) {
              continue;
            }

            // Track this fight to avoid duplicates
            if (fight.fight_id) {
              processedFightIds.add(fight.fight_id);
            }

            const opponent = fight.opponent_manager_name;
            const opponentRace = fight.opponent_race || 'Unknown';
            if (!opponent) continue;

            // Track vs opponent manager
            if (!managerRecords[opponent]) {
              managerRecords[opponent] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            // Track race vs race matchups
            if (!raceVsRace[warriorRace]) {
              raceVsRace[warriorRace] = {};
            }
            if (!raceVsRace[warriorRace][opponentRace]) {
              raceVsRace[warriorRace][opponentRace] = { wins: 0, losses: 0, kills: 0, slain: 0 };
            }

            // Track weapon performance (use weapon_name from fight_history, fall back to primary_weapon)
            const weapon = fight.weapon_name || fight.primary_weapon || 'Unknown';
            if (!weaponRecords[weapon]) {
              weaponRecords[weapon] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            // Track weapon+race performance
            if (!weaponByRace[weapon]) {
              weaponByRace[weapon] = {};
            }
            if (!weaponByRace[weapon][warriorRace]) {
              weaponByRace[weapon][warriorRace] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            // Track weapon+race+warrior performance
            if (!weaponByRaceByWarrior[weapon]) {
              weaponByRaceByWarrior[weapon] = {};
            }
            if (!weaponByRaceByWarrior[weapon][warriorRace]) {
              weaponByRaceByWarrior[weapon][warriorRace] = {};
            }
            if (!weaponByRaceByWarrior[weapon][warriorRace][warrior.name]) {
              weaponByRaceByWarrior[weapon][warriorRace][warrior.name] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
            }

            if (fight.result === 'win') {
              managerRecords[opponent].wins++;
              raceRecords[warriorRace].wins++;
              raceVsRace[warriorRace][opponentRace].wins++;
              weaponRecords[weapon].wins++;
              weaponByRace[weapon][warriorRace].wins++;
              weaponByRaceByWarrior[weapon][warriorRace][warrior.name].wins++;
              totalWins++;
            } else if (fight.result === 'loss') {
              managerRecords[opponent].losses++;
              raceRecords[warriorRace].losses++;
              raceVsRace[warriorRace][opponentRace].losses++;
              weaponRecords[weapon].losses++;
              weaponByRace[weapon][warriorRace].losses++;
              weaponByRaceByWarrior[weapon][warriorRace][warrior.name].losses++;
              totalLosses++;
            }

            if (fight.opponent_slain) {
              managerRecords[opponent].kills++;
              raceRecords[warriorRace].kills++;
              raceVsRace[warriorRace][opponentRace].kills++;
              weaponRecords[weapon].kills++;
              weaponByRace[weapon][warriorRace].kills++;
              weaponByRaceByWarrior[weapon][warriorRace][warrior.name].kills++;
              totalKills++;
            }

            if (fight.warrior_slain) {
              managerRecords[opponent].deaths++;
              weaponRecords[weapon].deaths++;
              weaponByRace[weapon][warriorRace].deaths++;
              weaponByRaceByWarrior[weapon][warriorRace][warrior.name].deaths++;
              totalDeaths++;
            }
          }
        };

        // Process fight history from active warriors
        if (teamData.warriors) {
          debugLog(`Processing ${teamData.warriors.length} active warriors from team ${teamData.team_id}`);
          for (const warrior of teamData.warriors) {
            if (warrior && warrior.name) {
              const fightCount = warrior.fight_history ? warrior.fight_history.length : 0;
              debugLog(`  Warrior "${warrior.name}": ${fightCount} fights`);
            }
            processFightHistory(warrior);
          }
        } else {
          debugLog(`Team ${teamData.team_id} has no warriors array`);
        }

        // Process fight history from archived warriors
        if (teamData.archived_warriors) {
          console.log(`Processing ${teamData.archived_warriors.length} archived warriors from team ${teamData.team_id}`);
          for (const archivedWarrior of teamData.archived_warriors) {
            processFightHistory(archivedWarrior);
          }
        }
      } catch (err) {
        console.error(`Error reading team file ${file}:`, err);
      }
    }

    // Apply accumulated slain counts to race records
    for (const race of Object.keys(raceRecords)) {
      raceRecords[race].slain = allSlainByRace[race] || 0;
    }

    // Also process fight_history from team files to capture current turn data not yet in league results
    for (const file of files) {
      try {
        const teamPath = pathLib.join(teamsDir, file);
        const teamData = JSON.parse(fs.readFileSync(teamPath, 'utf8'));

        if (teamData.manager_name !== managerName) continue;
        const leagueTeamIds = [38, 39, 40, 83, 94];
        if (!leagueTeamIds.includes(teamData.team_id)) continue;

        // Process active warriors' fight history
        if (teamData.warriors) {
          for (const warrior of teamData.warriors) {
            if (!warrior || !warrior.fight_history) continue;

            const race = warrior.race || 'Unknown';
            const warriorPrimaryWeapon = warrior.primary_weapon || 'Open Hand';

            for (const fight of warrior.fight_history) {
              // Skip if we already processed this fight from league results
              if (fight.fight_id && processedFightIds.has(fight.fight_id)) {
                continue;
              }

              const opponent = fight.opponent_manager_name;
              if (!opponent) continue;

              // Use fight's primary_weapon if available, otherwise use warrior's current weapon
              const weapon = fight.primary_weapon || warriorPrimaryWeapon;

              // Initialize records if needed
              if (!managerRecords[opponent]) {
                managerRecords[opponent] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }
              if (!raceRecords[race]) {
                raceRecords[race] = { wins: 0, losses: 0, kills: 0, deaths: 0, slain: 0 };
              }
              if (!weaponRecords[weapon]) {
                weaponRecords[weapon] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }
              if (!weaponByRace[weapon]) {
                weaponByRace[weapon] = {};
              }
              if (!weaponByRace[weapon][race]) {
                weaponByRace[weapon][race] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              // Track warrior+weapon+race performance
              const warriorNameFromFight = warrior.name;
              if (!weaponByRaceByWarrior[weapon]) {
                weaponByRaceByWarrior[weapon] = {};
              }
              if (!weaponByRaceByWarrior[weapon][race]) {
                weaponByRaceByWarrior[weapon][race] = {};
              }
              if (!weaponByRaceByWarrior[weapon][race][warriorNameFromFight]) {
                weaponByRaceByWarrior[weapon][race][warriorNameFromFight] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              if (fight.result === 'win') {
                managerRecords[opponent].wins++;
                raceRecords[race].wins++;
                weaponRecords[weapon].wins++;
                weaponByRace[weapon][race].wins++;
                weaponByRaceByWarrior[weapon][race][warriorNameFromFight].wins++;
                totalWins++;
              } else if (fight.result === 'loss') {
                managerRecords[opponent].losses++;
                raceRecords[race].losses++;
                weaponRecords[weapon].losses++;
                weaponByRace[weapon][race].losses++;
                weaponByRaceByWarrior[weapon][race][warriorNameFromFight].losses++;
                totalLosses++;
              }

              if (fight.opponent_slain) {
                managerRecords[opponent].kills++;
                raceRecords[race].kills++;
                weaponRecords[weapon].kills++;
                weaponByRace[weapon][race].kills++;
                weaponByRaceByWarrior[weapon][race][warriorNameFromFight].kills++;
                totalKills++;
              }

              if (fight.warrior_slain) {
                managerRecords[opponent].deaths++;
                raceRecords[race].deaths++;
                weaponRecords[weapon].deaths++;
                weaponByRace[weapon][race].deaths++;
                weaponByRaceByWarrior[weapon][race][warriorNameFromFight].deaths++;
                totalDeaths++;
              }
            }
          }
        }

        // Process archived warriors' fight history
        if (teamData.archived_warriors) {
          for (const archivedWarrior of teamData.archived_warriors) {
            if (!archivedWarrior || !archivedWarrior.fight_history) continue;

            const race = archivedWarrior.race || 'Unknown';
            const archivedPrimaryWeapon = archivedWarrior.primary_weapon || 'Open Hand';

            for (const fight of archivedWarrior.fight_history) {
              // Skip if we already processed this fight from league results
              if (fight.fight_id && processedFightIds.has(fight.fight_id)) {
                continue;
              }

              const opponent = fight.opponent_manager_name;
              if (!opponent) continue;

              // Use fight's primary_weapon if available, otherwise use warrior's recorded weapon
              const weapon = fight.primary_weapon || archivedPrimaryWeapon;

              // Initialize records if needed
              if (!managerRecords[opponent]) {
                managerRecords[opponent] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }
              if (!raceRecords[race]) {
                raceRecords[race] = { wins: 0, losses: 0, kills: 0, deaths: 0, slain: 0 };
              }
              if (!weaponRecords[weapon]) {
                weaponRecords[weapon] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }
              if (!weaponByRace[weapon]) {
                weaponByRace[weapon] = {};
              }
              if (!weaponByRace[weapon][race]) {
                weaponByRace[weapon][race] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              // Track warrior+weapon+race performance for archived warrior
              const archivedWarriorName = archivedWarrior.name;
              if (!weaponByRaceByWarrior[weapon]) {
                weaponByRaceByWarrior[weapon] = {};
              }
              if (!weaponByRaceByWarrior[weapon][race]) {
                weaponByRaceByWarrior[weapon][race] = {};
              }
              if (!weaponByRaceByWarrior[weapon][race][archivedWarriorName]) {
                weaponByRaceByWarrior[weapon][race][archivedWarriorName] = { wins: 0, losses: 0, kills: 0, deaths: 0 };
              }

              if (fight.result === 'win') {
                managerRecords[opponent].wins++;
                raceRecords[race].wins++;
                weaponRecords[weapon].wins++;
                weaponByRace[weapon][race].wins++;
                weaponByRaceByWarrior[weapon][race][archivedWarriorName].wins++;
                totalWins++;
              } else if (fight.result === 'loss') {
                managerRecords[opponent].losses++;
                raceRecords[race].losses++;
                weaponRecords[weapon].losses++;
                weaponByRace[weapon][race].losses++;
                weaponByRaceByWarrior[weapon][race][archivedWarriorName].losses++;
                totalLosses++;
              }

              if (fight.opponent_slain) {
                managerRecords[opponent].kills++;
                raceRecords[race].kills++;
                weaponRecords[weapon].kills++;
                weaponByRace[weapon][race].kills++;
                weaponByRaceByWarrior[weapon][race][archivedWarriorName].kills++;
                totalKills++;
              }

              if (fight.warrior_slain) {
                managerRecords[opponent].deaths++;
                raceRecords[race].deaths++;
                weaponRecords[weapon].deaths++;
                weaponByRace[weapon][race].deaths++;
                weaponByRaceByWarrior[weapon][race][archivedWarriorName].deaths++;
                totalDeaths++;
              }
            }
          }
        }
      } catch (err) {
        // Silently skip files that can't be processed
      }
    }

    // Convert to sorted arrays
    const records = Object.entries(managerRecords)
      .map(([opponent, stats]) => ({ opponent, ...stats }))
      .sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses));

    const raceRecordsArray = Object.entries(raceRecords)
      .map(([race, stats]) => ({ race, ...stats }))
      .sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses));

    // Convert race vs race to sorted array format
    const raceVsRaceArray = Object.entries(raceVsRace)
      .map(([attackerRace, opponents]) => ({
        race: attackerRace,
        matchups: Object.entries(opponents)
          .map(([opponentRace, stats]) => ({ opponent_race: opponentRace, ...stats }))
          .sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses))
      }))
      .sort((a, b) => {
        const aTotal = Object.values(a.matchups).reduce((sum, m) => sum + m.wins + m.losses, 0);
        const bTotal = Object.values(b.matchups).reduce((sum, m) => sum + m.wins + m.losses, 0);
        return bTotal - aTotal;
      });

    // Convert weapon records to sorted array format with race and warrior breakdown
    const weaponRecordsArray = Object.entries(weaponRecords)
      .map(([weapon, stats]) => {
        const raceBreakdown = Object.entries(weaponByRace[weapon] || {})
          .map(([race, raceStats]) => {
            const warriorBreakdown = Object.entries(weaponByRaceByWarrior[weapon]?.[race] || {})
              .map(([warrior, warriorStats]) => ({ warrior, ...warriorStats }))
              .sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses));
            return { race, ...raceStats, warrior_breakdown: warriorBreakdown };
          })
          .sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses));
        return { weapon, ...stats, race_breakdown: raceBreakdown };
      })
      .sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses));

    // Calculate cumulative record from all teams' turn history
    let cumulativeWins = 0, cumulativeLosses = 0, cumulativeKills = 0;
    for (const file of files) {
      try {
        const teamPath = pathLib.join(teamsDir, file);
        const teamData = JSON.parse(fs.readFileSync(teamPath, 'utf8'));

        if (teamData.manager_name !== managerName) continue;

        // Check if this team is in the league (if we discovered league teams)
        if (leagueTeamIds.size > 0 && !leagueTeamIds.has(teamData.team_id)) {
          continue;
        }

        // Sum up turn_history records
        if (teamData.turn_history && Array.isArray(teamData.turn_history)) {
          for (const turn of teamData.turn_history) {
            cumulativeWins += turn.w || 0;
            cumulativeLosses += turn.l || 0;
            cumulativeKills += turn.k || 0;
          }
        }
      } catch (err) {
        // Silently skip files that can't be parsed
      }
    }

    return {
      success: true,
      manager: managerName,
      records,
      race_records: raceRecordsArray,
      race_vs_race: raceVsRaceArray,
      weapon_records: weaponRecordsArray,
      totals: { wins: totalWins, losses: totalLosses, kills: totalKills, deaths: totalDeaths },
      cumulative_record: { wins: cumulativeWins, losses: cumulativeLosses, kills: cumulativeKills }
    };
  } catch (err) {
    console.error('Error getting manager record:', err);
    return { success: false, error: err.message };
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});