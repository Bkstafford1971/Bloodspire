if (require('electron-squirrel-startup')) return;

const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const pathLib = require('path');
const fs = require('fs-extra');

// Disable hardware acceleration to resolve UI focus and rendering issues
app.disableHardwareAcceleration();


// Global variable to store the base directory path
let baseDir = null;
let mainWindow;

const configPath = pathLib.join(app.getPath('userData'), 'config.json');

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