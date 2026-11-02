# Installs the ReActor face swap add-on into the portable ComfyUI, so BASIC_OS photos about a player
# use that player's face from his game portrait.
#
# What it installs (about 1 GB of downloads):
#   - ComfyUI-ReActor v0.7.1 (custom node, from github.com/Gourieff/ComfyUI-ReActor)
#   - insightface 0.7.3 (prebuilt Windows wheel for Python 3.13, from github.com/Gourieff/Assets)
#   - onnxruntime-gpu plus ReActor's requirements, only versions published at least 14 days ago
#   - inswapper_128.onnx (face swap model) and GFPGANv1.4.pth (face cleanup model)
#
# Your current packages are saved first; to undo, see the instructions printed at the end.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File .\install_face_swap.ps1

$ErrorActionPreference = 'Stop'
$ComfyDir   = if ($env:COMFYUI_DIR) { $env:COMFYUI_DIR } else { Join-Path $HOME 'ComfyUI_windows_portable' }
$Python     = Join-Path $ComfyDir 'python_embeded\python.exe'
$NodesDir   = Join-Path $ComfyDir 'ComfyUI\custom_nodes'
$ReactorDir = Join-Path $NodesDir 'comfyui-reactor'
$ModelsDir  = Join-Path $ComfyDir 'ComfyUI\models'
$WorkDir    = Join-Path $ComfyDir 'basic_os_install'
$ReactorTag = 'v0.7.1'
$WheelUrl   = 'https://github.com/Gourieff/Assets/raw/main/Insightface/insightface-0.7.3-cp313-cp313-win_amd64.whl'
$Models = @(
    @{ Url = 'https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/inswapper_128.onnx'; Dir = 'insightface' },
    @{ Url = 'https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/GFPGANv1.4.pth'; Dir = 'facerestore_models' }
)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Yellow }

if (-not (Test-Path $Python)) { throw "ComfyUI's Python wasn't found at $Python. Set COMFYUI_DIR to your ComfyUI_windows_portable folder." }

# ComfyUI must be closed while its packages change
try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -UseBasicParsing -TimeoutSec 2 | Out-Null
    throw 'ComfyUI is running. Close its window (or the python window running it), then run this script again.'
} catch [System.Net.WebException] { }

New-Item -ItemType Directory -Force $WorkDir | Out-Null

Step 'Saving your current ComfyUI package list (for undo)'
$Backup = Join-Path $WorkDir ("packages_before_reactor_{0:yyyyMMdd_HHmmss}.txt" -f (Get-Date))
& $Python -m pip freeze | Out-File -Encoding utf8 $Backup
Write-Host "  Saved to $Backup"

Step "Downloading ComfyUI-ReActor $ReactorTag"
if (Test-Path $ReactorDir) {
    Write-Host '  Already present, skipping.'
} else {
    $Zip = Join-Path $WorkDir 'reactor.zip'
    Invoke-WebRequest -Uri "https://github.com/Gourieff/ComfyUI-ReActor/archive/refs/tags/$ReactorTag.zip" -OutFile $Zip -UseBasicParsing
    Expand-Archive -Path $Zip -DestinationPath $WorkDir -Force
    Move-Item (Join-Path $WorkDir "ComfyUI-ReActor-$($ReactorTag.TrimStart('v'))") $ReactorDir
}

Step 'Downloading the insightface wheel'
$Wheel = Join-Path $WorkDir 'insightface-0.7.3-cp313-cp313-win_amd64.whl'
if (-not (Test-Path $Wheel)) { Invoke-WebRequest -Uri $WheelUrl -OutFile $Wheel -UseBasicParsing }

Step 'Installing Python packages (torch is pinned so your CUDA build is kept)'
$Constraints = Join-Path $WorkDir 'constraints.txt'
$pinned = & $Python -c "import torch, torchvision, torchaudio, numpy; print(f'torch=={torch.__version__}\ntorchvision=={torchvision.__version__}\ntorchaudio=={torchaudio.__version__}\nnumpy=={numpy.__version__}')"
$pinned | Out-File -Encoding ascii $Constraints
& $Python -m pip install --no-warn-script-location --uploaded-prior-to P14D -c $Constraints `
    $Wheel onnxruntime-gpu -r (Join-Path $ReactorDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip install failed (see the messages above). Nothing else was changed after the package step.' }

Step 'Downloading the face models'
foreach ($m in $Models) {
    $dir = Join-Path $ModelsDir $m.Dir
    New-Item -ItemType Directory -Force $dir | Out-Null
    $file = Join-Path $dir ([IO.Path]::GetFileName($m.Url))
    if (Test-Path $file) { Write-Host "  $([IO.Path]::GetFileName($file)) already present."; continue }
    Write-Host "  $([IO.Path]::GetFileName($file))..."
    Invoke-WebRequest -Uri $m.Url -OutFile $file -UseBasicParsing
}

Step 'Checking the install'
& $Python -c "import insightface, onnxruntime; print('insightface', insightface.__version__, '| onnxruntime', onnxruntime.__version__, onnxruntime.get_available_providers())"

Write-Host "`nDone. Start BASIC_OS (or ComfyUI) again; photos about a player will now use his portrait face." -ForegroundColor Green
Write-Host "To undo: delete $ReactorDir, then run:" -ForegroundColor DarkGray
Write-Host "  & '$Python' -m pip install -r '$Backup'" -ForegroundColor DarkGray
