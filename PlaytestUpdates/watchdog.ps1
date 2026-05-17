# Bloodspire League Server Watchdog
# Runs every 5 minutes via Task Scheduler.
# Pings /api/ping; if the server doesn't respond it kills any stale process
# and restarts league_server.py silently in the background.
#
# Setup: run setup_watchdog.bat once as Administrator to register the task.

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$PingUrl      = "http://localhost:8766/api/ping"
$HostPassword = "password"   # Must match START_LEAGUE_SERVER.bat
$LogFile      = Join-Path $ScriptDir "watchdog.log"
$MaxLogBytes  = 100KB

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$ts] $Msg" -Encoding UTF8
    # Trim log when it grows too large
    $item = Get-Item $LogFile -ErrorAction SilentlyContinue
    if ($item -and $item.Length -gt $MaxLogBytes) {
        $lines = Get-Content $LogFile
        $lines | Select-Object -Last 200 | Set-Content $LogFile -Encoding UTF8
    }
}

# ── 1. Check if server is responding ──────────────────────────────────────
$up = $false
try {
    $r = Invoke-WebRequest -Uri $PingUrl -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    if ($r.StatusCode -eq 200) { $up = $true }
} catch {}

if ($up) { exit 0 }   # All good — nothing to do

Write-Log "Server not responding at $PingUrl — initiating restart"

# ── 2. Kill any stale Python process running league_server.py ─────────────
$stale = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*league_server*" }

foreach ($p in $stale) {
    Write-Log "  Terminating stale process PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($stale) { Start-Sleep -Seconds 3 }

# ── 3. Locate Python ──────────────────────────────────────────────────────
$PythonExe = (Get-Command "python.exe" -ErrorAction SilentlyContinue)?.Source
if (-not $PythonExe) {
    # Fallback: common install locations
    $PythonExe = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $PythonExe) {
    Write-Log "ERROR: python.exe not found — cannot restart server"
    exit 1
}

# ── 4. Start the server (hidden, no console window) ───────────────────────
try {
    $proc = Start-Process `
        -FilePath         $PythonExe `
        -ArgumentList     "league_server.py", "--host-password", $HostPassword `
        -WorkingDirectory $ScriptDir `
        -WindowStyle      Hidden `
        -PassThru

    Write-Log "Restarted league_server.py (PID $($proc.Id)) using $PythonExe"
} catch {
    Write-Log "ERROR starting server: $_"
    exit 1
}
