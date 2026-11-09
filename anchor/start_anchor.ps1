$ErrorActionPreference = "Stop"
$py = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$root = "D:\si_nemd"
Push-Location $root

& $py ".\tools\new_run.py" --config ".\anchor\params.anchor.json" --scan-id ANCHOR3 `
    --geom ".\structures\ANCHOR.geom.json" --structure ".\structures\ANCHOR.data" `
    --potentials ".\anchor\potentials.in" --scan-csv ".\anchor\scan_anchor.csv"
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\anchor\run_anchor.ps1"
$code = $LASTEXITCODE
Pop-Location
exit $code
