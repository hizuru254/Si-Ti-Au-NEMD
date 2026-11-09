# =============================================================================
# run_seed.ps1 -- launch exactly one seed, capture exit code and wall time.
# Never overwrites an existing log.pattern. Does not decide pass/fail.
# Usage:
#   pwsh -File tools/run_seed.ps1 -RunDir workspace/run_v001 -Seed 1001
# =============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RunDir,
    [Parameter(Mandatory = $true)][int]$Seed,
    [int]$TimeoutSeconds = 0
)

$ErrorActionPreference = "Stop"

$runDir = (Resolve-Path -LiteralPath $RunDir).Path
$seedDir = Join-Path $runDir ("seed_{0}" -f $Seed)
if (-not (Test-Path -LiteralPath $seedDir)) {
    Write-Error "seed 目录不存在: $seedDir"
    exit 2
}
$inFile = Join-Path $seedDir "in.pattern"
if (-not (Test-Path -LiteralPath $inFile)) {
    Write-Error "缺少输入脚本: $inFile"
    exit 2
}
$logFile = Join-Path $seedDir "log.pattern"
if (Test-Path -LiteralPath $logFile) {
    Write-Error "log.pattern 已存在，禁止覆盖: $logFile"
    exit 2
}

$paramsPath = Join-Path $runDir "params.snapshot.json"
$params = Get-Content -LiteralPath $paramsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$launch = $params.lammps.launch_mode
$exe = $params.lammps.exe
$ranks = [int]$params.lammps.mpi_ranks
$omp = [int]$params.lammps.omp_threads

if ($TimeoutSeconds -le 0) { $TimeoutSeconds = [int]$params.timeouts_s.seed }

$env:OMP_NUM_THREADS = "$omp"

if ($launch -eq "mpi") {
    $fileName = $params.lammps.mpiexec
    $argList = @("-n", "$ranks", $exe, "-in", "in.pattern", "-log", "log.pattern")
} elseif ($launch -eq "serial") {
    $fileName = $exe
    $argList = @("-in", "in.pattern", "-log", "log.pattern")
} else {
    Write-Error "未知 launch_mode: $launch"
    exit 2
}

$stdout = Join-Path $seedDir "screen.txt"
$stderr = Join-Path $seedDir "screen.err.txt"
$started = Get-Date
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$timedOut = $false

$p = Start-Process -FilePath $fileName -ArgumentList $argList `
    -WorkingDirectory $seedDir -NoNewWindow -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr

$ms = $TimeoutSeconds * 1000
if (-not $p.WaitForExit($ms)) {
    $timedOut = $true
    try { $p.Kill() } catch { }
    $p.WaitForExit(30000) | Out-Null
}
$p.Refresh()
$sw.Stop()
$code = if ($timedOut) { 124 } else { [int]$p.ExitCode }

$meta = [ordered]@{
    schema_version = "1.0"
    seed           = $Seed
    command        = "$fileName $($argList -join ' ')"
    launch_mode    = $launch
    mpi_ranks      = $ranks
    omp_threads    = $omp
    started_at     = $started.ToString("o")
    wall_time_s    = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    timed_out      = $timedOut
    exit_code      = $code
    host           = $env:COMPUTERNAME
}
$meta | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $seedDir "run_meta.json") -Encoding UTF8

Write-Output ("[RUN] {0}/{1} exit={2} wall={3}s timed_out={4}" -f (Split-Path $runDir -Leaf), (Split-Path $seedDir -Leaf), $code, $meta.wall_time_s, $timedOut)
exit $code
