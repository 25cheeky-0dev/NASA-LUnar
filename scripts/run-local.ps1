param([int]$Port = 8010, [switch]$Gemini)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:WISPR_STATIC_DIR = Join-Path $repo 'frontend/dist'
$env:CELESTIAL_CACHE_DIR = Join-Path $repo 'backend/data/celestial'
if (-not $env:WISPR_GLOBAL_ROOT) { $env:WISPR_GLOBAL_ROOT = Join-Path $repo 'backend/data/lunar-v1' }
if (-not $env:WISPR_DB_PATH) { $env:WISPR_DB_PATH = Join-Path $repo 'backend/data/wispr.sqlite3' }
if ($Gemini) {
    $secureKey = Read-Host 'Enter a NEW Gemini API key (hidden; kept in this process only)' -AsSecureString
    $env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
    $env:GEMINI_MODEL = Read-Host 'Enter the Gemini model ID enabled for your account'
}
Push-Location (Join-Path $repo 'backend')
try { & .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 }
finally { Pop-Location; if ($Gemini) { Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue } }
