$ErrorActionPreference = "Stop"
chcp 65001 > $null
$env:PYTHONIOENCODING = "utf-8"
$py = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$root = "D:\si_nemd"
Push-Location $root

& $py ".\tools\preflight.py" --config ".\anchor\params.relax11.json" `
    --geom ".\structures\ANCHOR11_relaxed.geom.json" --structure ".\structures\ANCHOR11_relaxed.data" `
    --potentials ".\anchor\potentials.in" --dry-run
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }

$out = & $py ".\tools\new_run.py" --config ".\anchor\params.relax11.json" --scan-id RELAX11 `
    --geom ".\structures\ANCHOR11_relaxed.geom.json" --structure ".\structures\ANCHOR11_relaxed.data" `
    --potentials ".\anchor\potentials.in" --scan-csv ".\anchor\scan_relax11.csv"
$out
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
$line = ($out | Where-Object { $_ -like "RUN_DIR=*" } | Select-Object -Last 1)
if (-not $line) { Write-Host "new_run 没有返回 RUN_DIR"; Pop-Location; exit 1 }
$run = $line.Substring(8)

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\anchor\run_anchor.ps1" -RunDir $run
$code = $LASTEXITCODE
Pop-Location
exit $code
