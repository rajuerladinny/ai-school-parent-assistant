# Start the Parent Assistant for a local demo (Windows PowerShell).
#
# Usage, from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
#
# Uses a fixed, publicly documented DEMO admin key. Fictional data only.
# Never use this script or this key for a real school or a public server.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if ($env:SCHOOL_ENV -eq "production") {
    Write-Error "start_demo.ps1 is for local demos only. Unset SCHOOL_ENV first."
}

$env:SCHOOL_ADMIN_KEY = "sunrise-demo-admin-key"

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "No .venv found. Run: python -m venv .venv; .venv\Scripts\pip install -r requirements-rag.txt"
}

Write-Host ""
Write-Host "Sunrise Valley demo starting at http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Staff portal admin key: $($env:SCHOOL_ADMIN_KEY)" -ForegroundColor Cyan
Write-Host "Walkthrough: docs\demo\DEMO_GUIDE.md. Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host ""

& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
