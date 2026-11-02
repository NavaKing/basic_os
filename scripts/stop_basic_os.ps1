# Stops BASIC_OS and the ComfyUI it starts in the background (ComfyUI has no window to close).
# Ollama is left running because other apps can share it; add -IncludeOllama to stop it too.

param([switch]$IncludeOllama)

$Ports = [ordered]@{ 5000 = 'BASIC_OS'; 8188 = 'ComfyUI' }

function Stop-Tree($id) {
    # BASIC_OS runs Flask in debug mode: a watcher process plus a child that serves the page, so stop the whole tree.
    # If the watcher already died, Windows still lists it as the port's owner; its orphaned child is found by parent id.
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Tree $_.ProcessId }
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}

Write-Host 'Stopping BASIC_OS' -ForegroundColor Yellow
foreach ($entry in $Ports.GetEnumerator()) {
    $owners = Get-NetTCPConnection -LocalPort $entry.Key -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        Stop-Tree $id
    }
    if ($owners) { Write-Host "  Stopped $($entry.Value)." -ForegroundColor Green } else { Write-Host "  $($entry.Value) wasn't running." }
}

Start-Sleep -Milliseconds 500
if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host '  Port 5000 is still in use; close any other python windows running app.py.' -ForegroundColor Red
}

if ($IncludeOllama) {
    Get-Process -Name 'ollama app', 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host '  Stopped Ollama.' -ForegroundColor Green
} else {
    Write-Host '  Ollama left running (other apps can share it). Quit it from its tray icon if you want.'
}
Start-Sleep -Seconds 3
