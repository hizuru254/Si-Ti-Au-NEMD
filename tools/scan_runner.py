#!/usr/bin/env python3
"""Batch orchestrator: run every pending row of scan.csv end-to-end.

For each point:
  build_geometry.py -> preflight (G0) -> new_run (G1) -> run seeds (G2)
  -> postprocess (G3) -> qc_check (G4) -> update scan status + summary

It never edits thresholds, never re-runs a failed seed and never invents data.
QC FAIL is a valid outcome and is recorded; infrastructure failures stop the
row (and optionally the batch).

Exit codes: 0 all rows attempted, 2 configuration/input error, 3 batch stopped.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402


def log(msg: str) -> None:
    print(f"[SCAN] {msg}", flush=True)


def load_space(path: Path) -> dict:
    return geomlib.load_json(path) if path.exists() else {}


def within_space(row: dict, space: dict) -> tuple[bool, str]:
    if not space.get("approved"):
        return False, "search_space.approved=false"
    kinds = space.get("kind") or []
    if kinds and row.get("kind", "flat") not in kinds:
        return False, f"kind={row.get('kind')} 不在批准范围"
    for key, col in (("W_nm", "W_nm"), ("D_nm", "D_nm"), ("P_nm", "P_nm"),
                     ("t_nm", "t_nm"), ("phi_deg", "phi_deg")):
        if key not in space or not space[key]:
            continue
        lo, hi = float(space[key][0]), float(space[key][1])
        try:
            v = float(row.get(col) or 0)
        except ValueError:
            return False, f"{col} 非数值"
        if not (lo - 1e-9 <= v <= hi + 1e-9):
            return False, f"{col}={v} 超出 [{lo},{hi}]"
    if space.get("sided") and row.get("sided", "single") not in space["sided"]:
        return False, f"sided={row.get('sided')} 不在批准范围"
    try:
        if float(row.get("P_nm") or 0) <= float(row.get("W_nm") or 0):
            return False, "P 必须大于 W"
        if space.get("max_D_A") and float(row.get("D_nm") or 0) * 10 > float(space["max_D_A"]):
            return False, f"D 超过 {space['max_D_A']} A"
    except ValueError:
        return False, "W/P/D 非数值"
    return True, "ok"


def run(cmd: list[str], cwd: Path, timeout: int, log_path: Path | None = None) -> int:
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("$ " + " ".join(str(c) for c in cmd) + "\n")
            fh.flush()
            p = subprocess.run(cmd, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout)
            return p.returncode
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       errors="replace", timeout=timeout)
    if p.returncode != 0:
        log(f"  rc={p.returncode}: {p.stderr.strip()[-500:]}")
    return p.returncode


def write_temp_params(config: Path, params: dict, out: Path, bin_a: float,
                      pilot: bool) -> None:
    p = json.loads(json.dumps(params))
    p["run"]["chunk_bin_A"] = float(bin_a)
    if pilot:
        p["seeds"] = [int(params["seeds"][0])]
        p["run"]["n_equil_steps"] = 1000
        p["run"]["n_prod_steps"] = 5000
        p["timeouts_s"]["seed"] = 3600
    out.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_status(tools: Path, scan_csv: Path, sid: str, status: str) -> None:
    subprocess.run([sys.executable, str(tools / "scan_status.py"), "--scan-csv",
                    str(scan_csv), "--scan-id", sid, "--status", status],
                   capture_output=True, text=True, errors="replace")


def mark(tools: Path, scan_csv: Path, sid: str, final: str) -> None:
    set_status(tools, scan_csv, sid, "running")
    set_status(tools, scan_csv, sid, final)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--scan-csv", required=True)
    ap.add_argument("--potentials", required=True)
    ap.add_argument("--builder", default=None)
    ap.add_argument("--template", default=None)
    ap.add_argument("--space", default=None)
    ap.add_argument("--max-points", type=int, default=0)
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--allow-draft", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stop-on-fail", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    params = geomlib.load_json(config_path)
    root = geomlib.resolve_project_root(config_path, params)
    tools = Path(__file__).resolve().parent
    builder = Path(args.builder) if args.builder else tools / "build_geometry.py"
    template = Path(args.template) if args.template else root / "templates" / "in.pattern.template"
    space = load_space(Path(args.space) if args.space else root / "config" / "search_space.json")
    scan_csv = Path(args.scan_csv).resolve()
    potentials = Path(args.potentials).resolve()
    structures = root / "structures"
    workspace = root / params.get("paths", {}).get("workspace", "workspace")
    run_log = workspace / "scan_runner.log"
    summary = workspace / "scan_summary.csv"

    if not builder.exists():
        log(f"builder 不存在: {builder}")
        return 2
    if not potentials.exists():
        log(f"potentials 不存在: {potentials}")
        return 2
    workspace.mkdir(parents=True, exist_ok=True)
    structures.mkdir(parents=True, exist_ok=True)

    with open(scan_csv, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    pending = [r for r in rows if (r.get("status") or "pending").strip() == "pending"]
    if args.max_points > 0:
        pending = pending[:args.max_points]
    if not pending:
        log("没有 pending 行")
        return 0

    log(f"pending={len(pending)} pilot={args.pilot} dry_run={args.dry_run}")
    for row in pending:
        sid = (row.get("scan_id") or "").strip()
        kind = (row.get("kind") or "flat").strip()
        W = float(row.get("W_nm") or 0)
        D = float(row.get("D_nm") or 0)
        P = float(row.get("P_nm") or 0)
        t = float(row.get("t_nm") or 0)
        phi = float(row.get("phi_deg") or 0)
        sided = (row.get("sided") or "single").strip()
        ti = float(space.get("fixed", {}).get("ti_A", 24.0))
        si = float(space.get("fixed", {}).get("si_A", 40.0))
        bin_a = float(space.get("fixed", {}).get("bin_A", 2.0 if kind != "flat" else 4.0))
        ok, why = within_space(row, space)
        status = "APPROVED" if ok else "DRAFT"
        if not ok and not args.allow_draft:
            log(f"{sid}: 跳过（{why}）；需要人类批准搜索空间或逐点放行")
            continue

        struct = structures / f"{sid}.data"
        geom = structures / f"{sid}.geom.json"
        cmds = [
            [sys.executable, str(builder), "--scan-id", sid, "--kind", kind,
             "--t-nm", str(t), "--ti", str(ti), "--si", str(si),
             "--W-nm", str(W), "--D-nm", str(D), "--P-nm", str(P),
             "--phi", str(phi), "--sided", sided, "--bin", str(bin_a),
             "--status", status, "--out-structure", str(struct), "--out-geom", str(geom)],
        ]
        if args.dry_run:
            log(f"{sid}: {kind} W={W} D={D} P={P} t={t} {sided} phi={phi} "
                f"ti={ti} bin={bin_a} status={status} -> {' '.join(cmds[0])}")
            continue

        tmp_params = config_path.parent / f".runner_{sid}.json"
        write_temp_params(config_path, params, tmp_params, bin_a, args.pilot)
        cfg = str(tmp_params)

        # 1 geometry
        rc = run(cmds[0], root, 600, run_log)
        if rc != 0:
            log(f"{sid}: build_geometry 失败 rc={rc}")
            mark(tools, scan_csv, sid, "failed")
            if args.stop_on_fail:
                return 3
            continue

        # 2 preflight
        rc = run([sys.executable, str(tools / "preflight.py"), "--config", cfg,
                  "--geom", str(geom), "--structure", str(struct),
                  "--potentials", str(potentials), "--template", str(template),
                  "--dry-run"], root, 1800, run_log)
        if rc != 0:
            log(f"{sid}: G0 失败 rc={rc}")
            mark(tools, scan_csv, sid, "failed")
            if args.stop_on_fail:
                return 3
            continue

        # 3 new run
        p = subprocess.run([sys.executable, str(tools / "new_run.py"), "--config", cfg,
                            "--scan-id", sid, "--geom", str(geom),
                            "--structure", str(struct), "--potentials", str(potentials),
                            "--scan-csv", str(scan_csv), "--template", str(template)],
                           cwd=str(root), capture_output=True, text=True, errors="replace")
        m = re.search(r"^RUN_DIR=(.+)$", p.stdout, re.M)
        if p.returncode != 0 or not m:
            log(f"{sid}: new_run 失败 rc={p.returncode} {p.stderr.strip()[-300:]}")
            mark(tools, scan_csv, sid, "failed")
            if args.stop_on_fail:
                return 3
            continue
        run_dir = Path(m.group(1).strip())
        set_status(tools, scan_csv, sid, "running")
        log(f"{sid}: run={run_dir.name}")

        # 4 seeds
        seeds = params["seeds"] if not args.pilot else [params["seeds"][0]]
        failed = False
        for seed in seeds:
            if os.name == "nt":
                cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                       "-File", str(tools / "run_seed.ps1"), "-RunDir", str(run_dir),
                       "-Seed", str(seed)]
            else:
                cmd = ["bash", str(tools / "run_seed.sh"), str(run_dir), str(seed)]
            rc = run(cmd, root, int(params["timeouts_s"]["seed"]) + 600, run_log)
            if rc != 0:
                log(f"{sid}: seed {seed} 失败 rc={rc}")
                failed = True
                break
        if failed:
            set_status(tools, scan_csv, sid, "failed")
            if args.stop_on_fail:
                return 3
            continue

        # 5 postprocess
        for seed in seeds:
            rc = run([sys.executable, str(tools / "postprocess.py"),
                      "--run-dir", str(run_dir), "--seed", f"seed_{seed}"], root, 600, run_log)
            if rc != 0:
                failed = True
                break
        if failed:
            log(f"{sid}: postprocess 失败")
            set_status(tools, scan_csv, sid, "failed")
            if args.stop_on_fail:
                return 3
            continue

        # 6 qc
        rc = run([sys.executable, str(tools / "qc_check.py"), "--run-dir", str(run_dir)],
                 root, 600, run_log)
        qc_path = run_dir / "qc.json"
        qc = geomlib.load_json(qc_path) if qc_path.exists() else {}
        passed = bool(qc.get("is_passed"))
        log(f"{sid}: QC {'PASS' if passed else 'FAIL'} TBR={qc.get('TBR_mean_m2KW')}")

        # 7 status + summary
        set_status(tools, scan_csv, sid, "done" if passed else "failed")

        new_file = not summary.exists()
        with open(summary, "a", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["timestamp", "scan_id", "run_id", "kind", "W_nm", "D_nm",
                            "P_nm", "t_nm", "phi_deg", "sided", "is_passed",
                            "TBR_mean", "TBR_relstd", "n_valid", "note"])
            w.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), sid,
                        run_dir.name, kind, W, D, P, t, phi, sided,
                        "True" if passed else "False", qc.get("TBR_mean_m2KW", ""),
                        qc.get("TBR_relstd", ""), qc.get("n_valid", ""), qc.get("note", "")])
        try:
            tmp_params.unlink()
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
