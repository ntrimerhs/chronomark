# Starts the FastAPI backend on http://localhost:8000
# Usage:  .\run-backend.ps1        (from the chronomark folder)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root 'venv\Scripts\python.exe'
$ffmpegDir = Join-Path $root 'tools\ffmpeg'

if (-not (Test-Path $py)) {
    throw "venv not found at $py -- run setup first."
}
# ffmpeg-python shells out to the ffmpeg/ffprobe binaries, which are not on the
# system PATH; the static build lives in tools\ffmpeg.
if (Test-Path $ffmpegDir) {
    $env:PATH = "$ffmpegDir;$env:PATH"
}

# Both embedding models are cached inside the project so the ~1 GB of weights is
# not re-downloaded into the user profile on a fresh checkout.
$modelCache = Join-Path $root 'models'
if (Test-Path $modelCache) {
    $env:HF_HOME = $modelCache
}

# qdrant_store.py opens ./qdrant_data relative to the working directory, and
# main.py writes uploads/, audio/, frames/ next to itself -- so run from backend\.
Set-Location (Join-Path $root 'backend')

Write-Host "Starting backend on http://localhost:8000 (Ctrl+C to stop)" -ForegroundColor Green
& $py -m uvicorn main:app --host 127.0.0.1 --port 8000
