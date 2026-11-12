#!/usr/bin/env python3
"""Parallel scan driver that respects the WSL2 ~48-rank ceiling.

Stage 1 (cheap): build_geometry -> preflight(G0) -> new_run(G1) for every pending row.
Stage 2 (expensive): run all (run_dir, seed) jobs through a worker pool, each job
        pinned to a disjoint CPU set (default 4 x 12 ranks = 48 ranks).
Stage 3 (cheap): postprocess -> qc_check -> scan.csv status + summary.

Never edits thresholds; never re-runs a failed seed; QC FAIL is recorded, not hidden.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402

LOCK = threading.Lock()


def log(msg: str) -> None:
    with LOCK:
        print(msg, flush=True)


def run(cmd, cwd, timeout, log_path=None, env=None):
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("$ " + " ".join(str(c) for c in cmd) + "\n")
            fh.flush()
            p = subprocess.run(cmd, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout, env=env)
            return p.returncode
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       errors="replace", timeout=timeout, env=env)
    return p.returncode


def within_space(row: dict, space: dict) -> tuple[bool, str]:
    if not space.get("approved"):
        return False, "search_space.approved=false"
    kinds = space.get("kind") or []
    if kinds and (row.get("kind") or "flat") not in kinds:
        return False, f"kind={row.get('kind')} not approved"
    for key in ("W_nm", "D_nm", "P_nm", "t_nm", "phi_deg"):
        if not space.get(key):
            continue
        lo, hi = float(space[key][0]), float(space[key][1])
        v = float(row.get(key) or 0)
        if not (lo - 1e-9 <= v <= hi + 1e-9):
            return False, f"{key}={v} out of [{lo},{hi}]"
    if space.get("sided") and (row.get("sided") or "single") not in space["sided"]:
        return False, f"sided={row.get('sided')} not approved"
    if float(row.get("P_nm") or 0) <= float(row.get("W_nm") or 0):
        return False, "P must exceed W"
    if space.get("max_D_A") and float(row.get("D_nm") or 0) * 10 > float(space["max_D_A"]):
        return False, f"D exceeds {space['max_D_A']} A"
    return True, "ok"


def set_status(tools: Path, scan_csv: Path, sid: str, status: str) -> None:
    subprocess.run([sys.executable, str(tools / "scan_status.py"), "--scan-csv",
                    str(scan_csv), "--scan-id", sid, "--status", status],
                   capture_output=True, text=True, errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--scan-csv", required=True)
    ap.add_argument("--potentials", required=True)
    ap.add_argument("--space", default="config/search_space.json")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ranks", type=int, default=12)
    ap.add_argument("--max-points", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-runs", action="store_true", help="only build+G0+new_run")
    ap.add_argument("--template", default=None, help="input template (default: repo template)")
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    params = geomlib.load_json(config_path)
    root = geomlib.resolve_project_root(config_path, params)
    tools = Path(__file__).resolve().parent
    space = geomlib.load_json(Path(args.space))
    scan_csv = Path(args.scan_csv).resolve()
    potentials = Path(args.potentials).resolve()
    structures = root / "structures"
    workspace = root / params.get("paths", {}).get("workspace", "workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    run_log = workspace / "scan_parallel.log"

    rows = list(csv.DictReader(open(scan_csv, "r", encoding="utf-8-sig", newline="")))
    pending = [r for r in rows if (r.get("status") or "pending").strip() == "pending"]
    if args.max_points:
        pending = pending[:args.max_points]
    log(f"[SCAN] pending={len(pending)} workers={args.workers} ranks={args.ranks}")
    if not pending:
        return 0

    # ---- stage 1: build / gate / create run ---------------------------------
    jobs = []
    for row in pending:
        sid = (row.get("scan_id") or "").strip()
        kind = (row.get("kind") or "flat").strip()
        ok, why = within_space(row, space)
        if not ok:
            log(f"[SCAN] {sid}: rejected ({why})")
            set_status(tools, scan_csv, sid, "failed")
            continue
        ti = float(space.get("fixed", {}).get("ti_A", 24.0))
        si = float(space.get("fixed", {}).get("si_A", 40.0))
        bin_a = float(space.get("fixed", {}).get("bin_A", 2.0))
        struct = structures / f"{sid}.data"
        geom = structures / f"{sid}.geom.json"
        cmd = [sys.executable, str(tools / "build_geometry.py"), "--scan-id", sid,
               "--kind", kind, "--t-nm", str(row.get("t_nm") or 4.0),
               "--ti", str(ti), "--si", str(si),
               "--W-nm", str(row.get("W_nm") or 0), "--D-nm", str(row.get("D_nm") or 0),
               "--P-nm", str(row.get("P_nm") or 0), "--phi", str(row.get("phi_deg") or 0),
               "--sided", (row.get("sided") or "single").strip(),
               "--bin", str(bin_a), "--status", "APPROVED",
               "--res-inset", str(params.get("protocol", {}).get("res_inset_A", 8.0)),
               "--out-structure", str(struct), "--out-geom", str(geom)]
        if args.dry_run:
            log("[SCAN] " + " ".join(cmd))
            continue
        if run(cmd, root, 1200, run_log) != 0:
            log(f"[SCAN] {sid}: build_geometry failed")
            set_status(tools, scan_csv, sid, "failed")
            continue
        pf = [sys.executable, str(tools / "preflight.py"), "--config", str(config_path),
              "--geom", str(geom), "--structure", str(struct),
              "--potentials", str(potentials), "--dry-run"]
        if args.template:
            pf += ["--template", str(Path(args.template).resolve())]
        rc = run(pf, root, 1800, run_log)
        if rc != 0:
            log(f"[SCAN] {sid}: G0 blocked")
            set_status(tools, scan_csv, sid, "failed")
            continue
        nr = [sys.executable, str(tools / "new_run.py"), "--config",
              str(config_path), "--scan-id", sid, "--geom", str(geom),
              "--structure", str(struct), "--potentials", str(potentials),
              "--scan-csv", str(scan_csv)]
        if args.template:
            nr += ["--template", str(Path(args.template).resolve())]
        p = subprocess.run(nr,
                           cwd=str(root), capture_output=True, text=True, errors="replace")
        m = re.search(r"^RUN_DIR=(.+)$", p.stdout, re.M)
        if p.returncode != 0 or not m:
            log(f"[SCAN] {sid}: new_run failed {p.stderr[-300:]}")
            set_status(tools, scan_csv, sid, "failed")
            continue
        run_dir = m.group(1).strip()
        set_status(tools, scan_csv, sid, "running")
        log(f"[SCAN] {sid}: {Path(run_dir).name}  W={row.get('W_nm')} D={row.get('D_nm')} "
            f"P={row.get('P_nm')} {row.get('sided')}")
        jobs.append({"sid": sid, "run_dir": Path(run_dir), "row": row})
    if args.skip_runs or args.dry_run:
        return 0

    # ---- stage 2: run seeds in parallel ------------------------------------
    slots = []
    for w in range(args.workers):
        lo = w * args.ranks
        slots.append(f"{lo}-{lo + args.ranks - 1}")
    free = list(slots)
    lock2 = threading.Lock()

    def take_slot():
        with lock2:
            return free.pop(0) if free else None

    def give_slot(s):
        with lock2:
            free.append(s)

    seeds = params["seeds"]
    tasks = [(j, s) for j in jobs for s in seeds]

    def launch(job, seed):
        slot = None
        while slot is None:
            slot = take_slot()
            if slot is None:
                import time
                time.sleep(1)
        env = dict(os.environ)
        env["MPIRUN_EXTRA"] = f"--cpu-set {slot}"
        cmd = ["bash", str(tools / "run_seed.sh"), str(job["run_dir"]), str(seed)]
        try:
            with open(workspace / "scan_parallel.log", "a", encoding="utf-8") as fh:
                fh.write(f"$ MPIRUN_EXTRA='--cpu-set {slot}' {' '.join(cmd)}\n")
            t0 = datetime.now()
            rc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True,
                                text=True, errors="replace",
                                timeout=int(params["timeouts_s"]["seed"]) + 600).returncode
            dt = (datetime.now() - t0).total_seconds()
        finally:
            give_slot(slot)
        return job, seed, rc, dt

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(launch, j, s) for (j, s) in tasks]
        for f in as_completed(futs):
            job, seed, rc, dt = f.result()
            log(f"[RUN] {job['sid']} seed={seed} rc={rc} wall={dt:.0f}s")
            results.append((job, seed, rc))

    # ---- stage 3: postprocess / qc -----------------------------------------
    summary = workspace / "scan_summary.csv"
    for job in jobs:
        ok = all(rc == 0 for (j, s, rc) in results if j is job)
        run_dir = job["run_dir"]
        if ok:
            for seed in seeds:
                run([sys.executable, str(tools / "postprocess.py"), "--run-dir",
                     str(run_dir), "--seed", f"seed_{seed}"], root, 600, run_log)
        qc_rc = run([sys.executable, str(tools / "qc_check.py"), "--run-dir", str(run_dir)],
                    root, 600, run_log)
        qc_path = run_dir / "qc.json"
        qc = geomlib.load_json(qc_path) if qc_path.exists() else {}
        passed = bool(qc.get("is_passed"))
        # Screening mode: with a single seed the group gate n_valid_ge_3 can never
        # pass.  For ranking we require every present seed to be individually valid.
        per_seed = qc.get("per_seed") or {}
        screen_ok = bool(per_seed) and all(v.get("valid") for v in per_seed.values())
        set_status(tools, scan_csv, job["sid"],
                   "done" if (passed or screen_ok) else "failed")
        new_file = not summary.exists()
        row = job["row"]
        with open(summary, "a", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["timestamp", "scan_id", "run_id", "kind", "W_nm", "D_nm", "P_nm",
                            "t_nm", "phi_deg", "sided", "is_passed", "TBR_mean", "TBR_relstd",
                            "n_valid", "screen_ok", "note"])
            w.writerow([datetime.now().astimezone().isoformat(timespec="seconds"),
                        job["sid"], run_dir.name, row.get("kind"), row.get("W_nm"),
                        row.get("D_nm"), row.get("P_nm"), row.get("t_nm"),
                        row.get("phi_deg"), row.get("sided"),
                        "True" if passed else "False", qc.get("TBR_mean_m2KW", ""),
                        qc.get("TBR_relstd", ""), qc.get("n_valid", ""),
                        "True" if screen_ok else "False", qc.get("note", "")])
        log(f"[QC] {job['sid']} full={'PASS' if passed else 'FAIL'} "
            f"screen={'OK' if screen_ok else 'FAIL'} TBR={qc.get('TBR_mean_m2KW')} note={qc.get('note','')[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
