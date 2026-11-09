$ErrorActionPreference = "Continue"
$ws = "D:\si_nemd\anchor\workspace"
$run = (Get-ChildItem $ws -Directory -Filter "run_v*" | Sort-Object Name | Select-Object -Last 1).FullName
$py = "C:\Users\绯鹤\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$log = Join-Path $ws "anchor_run.log"
"START $(Get-Date -Format o)  run=$run" | Out-File -FilePath $log -Encoding utf8

foreach ($s in 1001, 2002, 3003) {
    "[SEED $s] $(Get-Date -Format o)" | Out-File -FilePath $log -Append -Encoding utf8
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\si_nemd\tools\run_seed.ps1" -RunDir $run -Seed $s *>> $log
    if ($LASTEXITCODE -ne 0) {
        "SEED $s FAILED rc=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
        exit 1
    }
}

foreach ($s in 1001, 2002, 3003) {
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
