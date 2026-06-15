if (require('electron-squirrel-startup')) return;

const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const pathLib = require('path');
const fs = require('fs-extra');
const https = require('https');
const { execFile } = require('child_process');
const os = require('os');

// Disable hardware acceleration to resolve UI focus and rendering issues
app.disableHardwareAcceleration();


// Global variable to store the base directory path
let baseDir = null;
let mainWindow;

const configPath = pathLib.join(app.getPath('userData'), 'config.json');
const { version: currentVersion } = require('./package.json');

// ============================================================
// AUTO-UPDATE LOGIC
// ============================================================

function fetchVersionInfo() {
  return new Promise((resolve, reject) => {
    const url = 'https://raw.githubusercontent.com/Bkstafford1971/Bloodspire/main/version.json';
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (err) {
          reject(new Error('Failed to parse version info'));
        }
      });
    }).on('error', reject);
  });
}

function downloadFile(url, destPath) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destPath);
    https.get(url, (res) => {
      res.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    }).on('error', (err) => {
      fs.remove(destPath);
      reject(err);
    });
  });
}

function compareVersions(v1, v2) {
  // Returns true if v2 > v1
  const p1 = v1.split('.').map(Number);
  const p2 = v2.split('.').map(Number);
  for (let i = 0; i < Math.max(p1.length, p2.length); i++) {
    const part1 = p1[i] || 0;
    const part2 = p2[i] || 0;
    if (part2 > part1) return true;
    if (part2 < part1) return false;
  }
  return false;
}

async function checkForUpdates() {
  try {
    const versionInfo = await fetchVersionInfo();

    if (compareVersions(currentVersion, versionInfo.version)) {
      // Update available
      const result = await dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: 'Update Available',
        message: `Bloodspire ${versionInfo.version} is available.`,
        detail: 'This update is required to continue. The new version will be downloaded and installed.',
        buttons: ['Install Update', 'Exit'],
        defaultId: 0,
        cancelId: 1
      });

      if (result.response === 0) {
        // User clicked "Install Update"
        await performUpdate(versionInfo);
      } else {
        // User clicked "Exit"
        app.quit();
      }
    }
  } catch (err) {
    console.error('Update check failed:', err);
    // Silently fail - don't block the app if update check fails
  }
}

async function performUpdate(versionInfo) {
  try {
    const tempDir = pathLib.join(os.tmpdir(), 'bloodspire-update');
    await fs.ensureDir(tempDir);

    const installerPath = pathLib.join(tempDir, `BloodspireArena-${versionInfo.version}-Setup.exe`);

    // Show progress dialog
    const progressWin = new BrowserWindow({
      width: 400,
      height: 150,
      parent: mainWindow,
      modal: true,
      show: true,
      webPreferences: { nodeIntegration: false }
    });

    progressWin.loadURL(`data:text/html,<html><body style="font-family:Arial;display:flex;flex-direction:column;justify-content:center;align-items:center;height:100%;background:#f0f0f0;"><h2>Downloading Update...</h2><p>This will take a moment.</p></body></html>`);

    // Download installer
    console.log('Downloading from:', versionInfo.downloadUrl);
    await downloadFile(versionInfo.downloadUrl, installerPath);

    if (!progressWin.isDestroyed()) {
      progressWin.close();
    }

    // Run installer with silent mode and no restart (we'll restart ourselves)
    console.log('Running installer:', installerPath);

    // Close the main app before running installer
    mainWindow.close();

    // Run installer silently - /S for silent, /NORESTART to prevent auto restart
    execFile(installerPath, ['/S', '/NORESTART'], (error) => {
      if (error) {
        console.error('Installer error:', error);
        dialog.showErrorBox('Update Failed', 'The update failed to install. Please download and install manually.');
        app.quit();
      } else {
        console.log('Installer completed, relaunching app');
        // NSIS installer will have updated the app, now restart it
        app.relaunch();
        app.quit();
      }
    });
  } catch (err) {
    console.error('Update error:', err);
    dialog.showErrorBox('Update Failed', 'Failed to download update: ' + err.message);
  }
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
      preload: typeof MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY !== 'undefined'
        ? MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY
        : pathLib.join(__dirname, 'preload.js'),
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
    mainWindow.loadFile(pathLib.join(__dirname, '..', 'bloodspire_client.html'));
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
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      checkForUpdates();
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
      await fs.writeJson(configPath, { baseDir: baseDir });
      console.log('Base directory set to:', baseDir);
    } catch (err) {
      console.error('Failed to save config:', err);
    }
    return baseDir;
  }
  return null;
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

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});