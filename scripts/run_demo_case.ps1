param(
    [ValidateSet('hf-incident', 'zero-accident-contractors')]
    [string]$Case = 'hf-incident',
    [int]$Port = 11506
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
python scripts/build_demo_cases.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$casePath = Join-Path $projectRoot "data\demo_cases\$Case.sqlite"
$env:PSM_WIZARD_DB_PATH = [System.IO.Path]::GetFullPath($casePath)
Write-Host "示範案例：$Case"
Write-Host "開啟 http://127.0.0.1:$Port/wizard/1"
python -m uvicorn psm.web:app --host 127.0.0.1 --port $Port
