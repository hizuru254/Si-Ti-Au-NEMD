#!/usr/bin/env bash
# =============================================================================
# run_seed.sh -- WSL/Linux counterpart of run_seed.ps1 (UNVERIFIED on target).
# Launches exactly one seed, records exit code and wall time, never overwrites
# an existing log.pattern.
# Usage: bash tools/run_seed.sh <run_dir> <seed>
# =============================================================================
set -uo pipefail

RUN_DIR="${1:?usage: run_seed.sh <run_dir> <seed>}"
SEED="${2:?usage: run_seed.sh <run_dir> <seed>}"
SEED_DIR="$RUN_DIR/seed_$SEED"

[[ -d "$SEED_DIR" ]] || { echo "missing $SEED_DIR" >&2; exit 2; }
[[ -f "$SEED_DIR/in.pattern" ]] || { echo "missing in.pattern" >&2; exit 2; }
if [[ -e "$SEED_DIR/log.pattern" ]]; then
  echo "log.pattern exists, refuse to overwrite: $SEED_DIR/log.pattern" >&2
  exit 2
fi

PARAMS="$RUN_DIR/params.snapshot.json"
[[ -f "$PARAMS" ]] || { echo "missing $PARAMS" >&2; exit 2; }

read_cfg() {
  python3 - "$PARAMS" "$1" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
keys = sys.argv[2].split(".")
val = cfg
for k in keys:
    val = val[k]
print(val)
PY
}

LAUNCH=$(read_cfg lammps.launch_mode)
NP=$(read_cfg lammps.mpi_ranks)
OMP=$(read_cfg lammps.omp_threads)
TIMEOUT=$(read_cfg timeouts_s.seed)
EXE=$(read_cfg lammps.exe)

export OMP_NUM_THREADS="$OMP"

cd "$SEED_DIR" || exit 2
START=$(date +%s)

if [[ "$LAUNCH" == "mpi" ]]; then
  # MPIRUN_EXTRA lets several concurrent jobs bind to disjoint core sets,
  # e.g. MPIRUN_EXTRA="--cpu-set 32-63" (OpenMPI 4.x).
  timeout "$TIMEOUT" mpirun -np "$NP" --bind-to core ${MPIRUN_EXTRA:-} "$EXE" \
    -in in.pattern -log log.pattern > screen.txt 2> screen.err.txt
else
  timeout "$TIMEOUT" "$EXE" \
    -in in.pattern -log log.pattern > screen.txt 2> screen.err.txt
fi
CODE=$?
END=$(date +%s)
WALL=$((END - START))

python3 - "$SEED" "$CODE" "$WALL" "$LAUNCH" "$NP" "$OMP" <<'PY'
import json, sys
seed, code, wall, launch, np_, omp = sys.argv[1:7]
json.dump({
    "schema_version": "1.0",
    "seed": int(seed),
    "launch_mode": launch,
    "mpi_ranks": int(np_),
    "omp_threads": int(omp),
    "exit_code": int(code),
    "wall_time_s": float(wall),
    "timed_out": int(code) == 124,
}, open("run_meta.json", "w", encoding="utf-8"), indent=2)
PY

echo "[RUN] $SEED_DIR exit=$CODE wall=${WALL}s"
exit "$CODE"
