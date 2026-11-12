#!/usr/bin/env python3
"""Rank scan runs by TBR with propagated uncertainty.

Reads every run_vNNN under the workspace that has a tbr_uncertainty.json
(or computes it on the fly), joins with scan metadata and writes a markdown
table + ranks.csv.  Runs are never modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="anchor/workspace")
    ap.add_argument("--out-md", default="optimization/scan_ranking.md")
    ap.add_argument("--out-csv", default="optimization/scan_ranking.csv")
    ap.add_argument("--min-dt-snr", type=float, default=0.0,
                    help="drop rows whose dT_total SNR is below this")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    rows = []
    for d in sorted(ws.iterdir()):
        if not d.is_dir() or not (d / "params.snapshot.json").exists():
            continue
        meta = geomlib.load_json(d / "run_meta.json") if (d / "run_meta.json").exists() else {}
        scan = meta.get("scan", {})
        seed = None
        for sd in d.glob("seed_*"):
            if (sd / "profile.txt").exists():
                seed = sd
                break
        if seed is None:
            continue
        unc = None
        if (seed / "tbr_uncertainty.json").exists():
            unc = geomlib.load_json(seed / "tbr_uncertainty.json")
        if unc is None:
            subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "tbr_uncertainty.py"),
                            "--run-dir", str(d), "--seed", seed.name],
                           capture_output=True, text=True)
            if (seed / "tbr_uncertainty.json").exists():
                unc = geomlib.load_json(seed / "tbr_uncertainty.json")
        if unc is None:
            continue
        qc = geomlib.load_json(d / "qc.json") if (d / "qc.json").exists() else {}
        tbr = unc["TBR_total_m2KW"]
        sig = unc["TBR_sem_m2KW"]
        snr_tot = unc["dT_total_K"] / unc["dT_total_sem_K"] if unc["dT_total_sem_K"] else 0.0
        if snr_tot < args.min_dt_snr:
            continue
        rows.append({
            "run_id": d.name,
            "scan_id": scan.get("scan_id", ""),
            "kind": scan.get("kind", ""),
            "W_nm": scan.get("W_nm", ""),
            "D_nm": scan.get("D_nm", ""),
            "P_nm": scan.get("P_nm", ""),
            "sided": scan.get("sided", ""),
            "duty": (f"{float(scan['W_nm']) / float(scan['P_nm']):.2f}"
                     if scan.get("W_nm") and scan.get("P_nm") and float(scan.get("P_nm") or 0) else ""),
            "TBR": tbr,
            "sigma": sig,
            "rel": sig / tbr if tbr else float("inf"),
            "dT_total": unc["dT_total_K"],
            "dT_sem": unc["dT_total_sem_K"],
            "snr": snr_tot,
            "tbr_postprocess": qc.get("TBR_mean_m2KW") or "",
            "qc_note": qc.get("note", "")[:60],
        })

    if not rows:
        print("[RANK] 没有可用数据")
        return 1
    rows.sort(key=lambda r: r["TBR"])
    best = rows[0]["TBR"]

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 图案扫描排名（协议 v1.3，按 TBR_total 升序）", "",
             "| # | scan | W(nm) | D(nm) | P(nm) | duty | sided | TBR (m²K/W) | ±σ | ±% | vs best |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['scan_id']} | {r['W_nm']} | {r['D_nm']} | {r['P_nm']} | {r['duty']} | "
            f"{r['sided']} | {r['TBR']:.3e} | {r['sigma']:.1e} | {100*r['rel']:.0f}% | "
            f"{r['TBR']/best:.2f}× |")
    lines += ["", f"最低 TBR 点：**{rows[0]['scan_id']}** ({rows[0]['run_id']})，"
                  f"TBR = {rows[0]['TBR']:.3e} ± {rows[0]['sigma']:.1e} m²K/W，"
                  f"dT_total = {rows[0]['dT_total']:.1f} ± {rows[0]['dT_sem']:.1f} K"]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(args.out_csv, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\n".join(lines))
    print(f"\n[RANK] {out_md}\n[RANK] {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
