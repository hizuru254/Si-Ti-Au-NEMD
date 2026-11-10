param([string]$RunDir = "")
$ErrorActionPreference = "Continue"
chcp 65001 > $null
$env:PYTHONIOENCODING = "utf-8"
$ws = "D:\si_nemd\anchor\workspace"
if ($RunDir) {
    $run = (Resolve-Path -LiteralPath $RunDir).Path
} else {
    $run = (Get-ChildItem $ws -Directory -Filter "run_v*" | Sort-Object Name | Select-Object -Last 1).FullName
}
$py = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$log = Join-Path $ws "anchor_run.log"
$params = Get-Content (Join-Path $run "params.snapshot.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$seeds = @($params.seeds)
if ($seeds.Count -eq 0) { Write-Host "params.snapshot.json 没有 seeds"; exit 1 }
"START $(Get-Date -Format o)  run=$run  seeds=$($seeds -join ',')" | Out-File -FilePath $log -Encoding utf8

foreach ($s in $seeds) {
    "[SEED $s] $(Get-Date -Format o)" | Out-File -FilePath $log -Append -Encoding utf8
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\si_nemd\tools\run_seed.ps1" -RunDir $run -Seed $s *>> $log
    if ($LASTEXITCODE -ne 0) {
        "SEED $s FAILED rc=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
        exit 1
    }
}

foreach ($s in $seeds) {
    "[POST seed_$s] $(Get-Date -Format o)" | Out-File -FilePath $log -Append -Encoding utf8
    & $py "D:\si_nemd\tools\postprocess.py" --run-dir $run --seed "seed_$s" *>> $log
    if ($LASTEXITCODE -ne 0) {
        "POST seed_$s FAILED rc=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
        exit 1
    }
}

"[QC] $(Get-Date -Format o)" | Out-File -FilePath $log -Append -Encoding utf8
& $py "D:\si_nemd\tools\qc_check.py" --run-dir $run *>> $log
"END $(Get-Date -Format o) qc_rc=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
exit $LASTEXITCODE
