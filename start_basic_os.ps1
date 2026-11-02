# Starts everything BASIC_OS needs (Ollama, ComfyUI, the Flask app) and opens it in the browser.
# Anything already running is left alone, so it's safe to run again. Each service gets its own
# minimized window: close that window to stop it.

param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$AppDir     = Join-Path $PSScriptRoot 'basic_os'
$ComfyDir   = if ($env:COMFYUI_DIR) { $env:COMFYUI_DIR } else { Join-Path $HOME 'ComfyUI_windows_portable' }
$OllamaApp  = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
$AppUrl     = 'http://127.0.0.1:5000'

function Test-Url($url) {
    try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

function Wait-Url($url, $name, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url $url) { Write-Host "  $name is ready." -ForegroundColor Green; return $true }
        Start-Sleep -Seconds 2
    }
    Write-Host "  $name didn't answer within $seconds seconds." -ForegroundColor Yellow
    return $false
}

Write-Host 'BASIC_OS launcher' -ForegroundColor Yellow

# 1. Ollama (text AI)
Write-Host '[1/3] Ollama'
if (Test-Url 'http://127.0.0.1:11434/api/tags') {
    Write-Host '  already running.' -ForegroundColor Green
} elseif (Test-Path $OllamaApp) {
    Start-Process -FilePath $OllamaApp
    Wait-Url 'http://127.0.0.1:11434/api/tags' 'Ollama' 60 | Out-Null
} else {
    Write-Host "  not found at $OllamaApp; articles and tweets won't generate." -ForegroundColor Yellow
}

# 2. ComfyUI (photos). The app can also start it on demand, but starting it now means the first render isn't slow.
Write-Host '[2/3] ComfyUI'
$ComfyPython = Join-Path $ComfyDir 'python_embeded\python.exe'
if (Test-Url 'http://127.0.0.1:8188/system_stats') {
    Write-Host '  already running.' -ForegroundColor Green
} elseif (Test-Path $ComfyPython) {
    Start-Process -FilePath $ComfyPython -WorkingDirectory $ComfyDir -WindowStyle Minimized `
        -ArgumentList '-s', 'ComfyUI\main.py', '--windows-standalone-build', '--disable-auto-launch', '--listen', '127.0.0.1', '--port', '8188'
    Wait-Url 'http://127.0.0.1:8188/system_stats' 'ComfyUI' 120 | Out-Null
} else {
    Write-Host "  not found in $ComfyDir; photos will be skipped." -ForegroundColor Yellow
}

# 3. The app itself
Write-Host '[3/3] BASIC_OS'
if (Test-Url $AppUrl) {
    Write-Host '  already running.' -ForegroundColor Green
} else {
    Start-Process -FilePath 'python' -ArgumentList 'app.py' -WorkingDirectory $AppDir -WindowStyle Minimized
    if (-not (Wait-Url $AppUrl 'BASIC_OS' 60)) {
        Write-Host '  Check the minimized "python" window for the error.' -ForegroundColor Red
        Read-Host 'Press Enter to close'
        exit 1
    }
}

if (-not $NoBrowser) { Start-Process $AppUrl }
Write-Host "BASIC_OS is running at $AppUrl. You can close this window." -ForegroundColor Green
Start-Sleep -Seconds 3
