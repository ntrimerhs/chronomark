# Starts the Vite dev server on http://localhost:5173
# Usage:  .\run-frontend.ps1      (from the chronomark folder)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$fe = Join-Path $root 'frontend'

if (-not (Test-Path (Join-Path $fe 'node_modules'))) {
    throw "node_modules missing -- run 'npm install' in $fe first."
}

Set-Location $fe
Write-Host "Starting frontend on http://localhost:5173 (Ctrl+C to stop)" -ForegroundColor Green
# The backend URL comes from frontend/src/config.js: defaults to localhost:8000,
# override with $env:VITE_API_URL before running this script.
if ($env:VITE_API_URL) { Write-Host "API base: $env:VITE_API_URL" }
npm run dev
