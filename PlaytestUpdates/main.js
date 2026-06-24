console.log('=== MAIN.JS LOADING ===');

if (require('electron-squirrel-startup')) {
  console.log('Squirrel startup detected, exiting');
  return;
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

// Set GitHub provider explicitly
if (process.env.GITHUB_TOKEN) {
  autoUpdater.setFeedURL({
    provider: 'github',
    owner: 'Bkstafford1971',
    repo: 'Bloodspire',
    token: process.env.GITHUB_TOKEN
  });
} else {
  autoUpdater.setFeedURL({
    provider: 'github',
    owner: 'Bkstafford1971',
    repo: 'Bloodspire'
  });
}


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
    logToFile('🔄 Starting update check...');
    logToFile('Current version: ' + currentVersion);

    autoUpdater.checkForUpdates()
      .then((result) => {
        logToFile('✓ Update check completed');
        logToFile('Result: ' + JSON.stringify(result, null, 2));

        if (result && result.updateInfo) {
          const newVersion = result.updateInfo.version;
          logToFile('Remote version: ' + newVersion);

          if (newVersion !== currentVersion) {
            updateAvailable = true;
            updateInfo = result.updateInfo;
            logToFile('✓ Update available: ' + newVersion);

            if (mainWindow && !mainWindow.isDestroyed()) {
              showUpdatePrompt(newVersion);
            }
          } else {
            logToFile('✓ App is up to date: ' + currentVersion);
          }
        } else {
          logToFile('⚠ No updateInfo in result');
        }
        resolve();
      })
      .catch((err) => {
        logToFile('✗ Update check failed: ' + err.message);
        logToFile('Full error: ' + JSON.stringify(err, null, 2));
        resolve();
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

  // Disable all UI interactions during update
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update:downloading');
  }

  autoUpdater.downloadUpdate()
    .then(() => {
      console.log('Update downloaded successfully');
      // Quit and install on next start
      autoUpdater.quitAndInstall();
    })
    .catch((err) => {
      console.error('Update download failed:', err);
      if (mainWindow && !mainWindow.isDestroyed()) {
        dialog.showErrorBox('Update Failed', 'Failed to download update: ' + err.message);
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
  setTimeout(() => {
    logToFile('500ms timeout reached, checking for updates...');
    if (mainWindow && !mainWindow.isDestroyed()) {
      logToFile('mainWindow exists, calling checkForUpdates()');
      checkForUpdates();
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
  console.log('data:getManagerRecord handler called for:', managerName);

  try {
    // Check for teams folder in both possible locations
    let teamsDir = pathLib.join(baseDir, 'teams');
    if (!fs.existsSync(teamsDir)) {
      teamsDir = pathLib.join(baseDir, 'saves', 'teams');
    }

    if (!fs.existsSync(teamsDir)) {
      return { success: false, error: `Teams directory not found. Checked: ${pathLib.join(baseDir, 'teams')} and ${pathLib.join(baseDir, 'saves', 'teams')}` };
    }

    const managerRecords = {};
    const raceRecords = {};
    const raceVsRace = {};
    let totalWins = 0, totalLosses = 0, totalKills = 0, totalDeaths = 0;

    // Read all team files
    const files = fs.readdirSync(teamsDir).filter(f => f.endsWith('.json') && !f.endsWith('.checksum'));

    for (const file of files) {
      try {
        const teamPath = pathLib.join(teamsDir, file);
        const teamData = JSON.parse(fs.readFileSync(teamPath, 'utf8'));

        if (teamData.manager_name !== managerName) continue;

        // Only count original 5 league teams
        const leagueTeamIds = [38, 39, 40, 83, 94];
        if (!leagueTeamIds.includes(teamData.team_id)) continue;

        // Build warrior race map
        const warriorRaces = {};
        if (teamData.warriors) {
          for (const w of teamData.warriors) {
            if (w && w.name) {
              warriorRaces[w.name] = w.race || 'Unknown';
            }
          }
        }

        // Count archived/dead warriors by race
        const slainByRace = {};
        if (teamData.archived_warriors) {
          for (const w of teamData.archived_warriors) {
            if (w && w.name && w.race) {
              slainByRace[w.race] = (slainByRace[w.race] || 0) + 1;
            }
          }
        }

        // Process fight history from each warrior
        if (teamData.warriors) {
          for (const warrior of teamData.warriors) {
            if (!warrior || !warrior.fight_history) continue;

            const warriorRace = warrior.race || 'Unknown';
            if (!raceRecords[warriorRace]) {
              raceRecords[warriorRace] = { wins: 0, losses: 0, kills: 0, deaths: 0, slain: slainByRace[warriorRace] || 0 };
            }

            for (const fight of warrior.fight_history) {
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

              if (fight.result === 'win') {
                managerRecords[opponent].wins++;
                raceRecords[warriorRace].wins++;
                raceVsRace[warriorRace][opponentRace].wins++;
                totalWins++;
              } else if (fight.result === 'loss') {
                managerRecords[opponent].losses++;
                raceRecords[warriorRace].losses++;
                raceVsRace[warriorRace][opponentRace].losses++;
                totalLosses++;
              }

              if (fight.opponent_slain) {
                managerRecords[opponent].kills++;
                raceRecords[warriorRace].kills++;
                raceVsRace[warriorRace][opponentRace].kills++;
                totalKills++;
              }

              if (fight.warrior_slain) {
                managerRecords[opponent].deaths++;
                totalDeaths++;
              }
            }
          }
        }
      } catch (err) {
        console.error(`Error reading team file ${file}:`, err);
      }
    }

    // Ensure all race records have slain count
    for (const race of Object.keys(raceRecords)) {
      if (!raceRecords[race].slain) {
        raceRecords[race].slain = slainByRace[race] || 0;
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

    return {
      success: true,
      manager: managerName,
      records,
      race_records: raceRecordsArray,
      race_vs_race: raceVsRaceArray,
      totals: { wins: totalWins, losses: totalLosses, kills: totalKills, deaths: totalDeaths }
    };
  } catch (err) {
    console.error('Error getting manager record:', err);
    return { success: false, error: err.message };
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});