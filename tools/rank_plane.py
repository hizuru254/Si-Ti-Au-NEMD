#!/usr/bin/env python3
"""Rank runs with the interface-model-free plane estimator.

Reads anchor/workspace/*/seed_*/tbr_planes.json (written by tools/tbr_plane.py)
and joins it with the scan metadata.  Runs without that file are computed on the
fly.

Usage:
  python3 tools/rank_plane.py [--workspace anchor/workspace] [--filter proto=1.6]
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="anchor/workspace")
    ap.add_argument("--z", type=float, default=84.0)
    ap.add_argument("--proto", default=None, help="keep only this protocol version")
    ap.add_argument("--out-csv", default=None)
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    rows = []
    for d in sorted(ws.iterdir()):
        if not d.is_dir() or not (d / "params.snapshot.json").exists():
            continue
        sd = next((s for s in d.glob("seed_*") if (s / "profile.txt").exists()), None)
        if sd is None:
            continue
        log = sd / "log.pattern"
        if not log.exists() or "Total wall time" not in log.read_text(errors="replace"):
            continue   # unfinished run (killed / still running)
        params = geomlib.load_json(d / "params.snapshot.json")
        proto = params.get("protocol", {}).get("version", "")
        if args.proto and proto != args.proto:
            continue
        jf = sd / "tbr_planes.json"
        if not jf.exists():
            subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "tbr_plane.py"),
                            "--run-dir", str(d), "--seed", sd.name, "--z", str(args.z)],
                           capture_output=True, text=True)
        if not jf.exists():
            continue
        u = geomlib.load_json(jf)
        meta = geomlib.load_json(d / "run_meta.json")
        scan = meta.get("scan", {})
        rows.append({
            "run": d.name, "scan": scan.get("scan_id", ""),
            "W": scan.get("W_nm", ""), "D": scan.get("D_nm", ""), "P": scan.get("P_nm", ""),
            "sided": scan.get("sided", ""), "flux": params["flux_ev_per_ps"],
            "proto": proto, "TBR": u["TBR_eff_m2KW"], "sem": u["TBR_sem"],
        })
    if not rows:
        print("[RANK] 无数据")
        return 1
    rows.sort(key=lambda r: r["TBR"])
    best = rows[0]["TBR"]
    print(f"{'run':9s} {'scan':9s} {'W':>5s} {'D':>4s} {'P':>4s} {'side':6s} {'q':>3s} "
          f"{'proto':5s} {'TBR_eff':>11s} {'+/-':>9s} {'vs best':>8s}")
    for r in rows:
        print(f"{r['run']:9s} {r['scan']:9s} {str(r['W']):>5s} {str(r['D']):>4s} "
              f"{str(r['P']):>4s} {r['sided']:6s} {r['flux']:3.0f} {r['proto']:5s} "
              f"{r['TBR']:11.3e} {r['sem']:9.2e} {r['TBR']/best:8.2f}x")
    if args.out_csv:
        with open(args.out_csv, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"[RANK] {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
