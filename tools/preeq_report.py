#!/usr/bin/env python3
"""Report dPE/dt convergence for a pre-equilibration run (protocol v1.4).

Reads <preeq-dir>/log.preeq (thermo every 1000 steps: step temp pe ke etotal)
and prints block-averaged PotEng drift, so the plateau can be judged.

Usage: python3 tools/preeq_report.py preeq/F000 [--last 0.5]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def parse(path: Path):
    tables = []
    hdr = None
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("Step"):
            if hdr is not None and rows:
                tables.append((hdr, rows))
            hdr = s.split()
            rows = []
            continue
        if hdr and s:
            parts = s.split()
            if len(parts) == len(hdr) and parts[0].isdigit():
                try:
                    rows.append([float(x) for x in parts])
                except ValueError:
                    pass
    if hdr is not None and rows:
        tables.append((hdr, rows))
    # keep the longest table (the run), ignoring the short minimize table
    tables = [(h, r) for h, r in tables if "PotEng" in h]
    if not tables:
        return None, None
    hdr, rows = max(tables, key=lambda hr: len(hr[1]))
    return hdr, np.array(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--last", type=float, default=0.5, help="fraction of the run to fit")
    args = ap.parse_args()
    d = Path(args.dir)
    hdr, a = parse(d / "log.preeq")
    if a is None:
        print(f"[PREEQ] {d}: 没有 thermo 数据")
        return 1
    idx = {n: hdr.index(n) for n in hdr}
    step = a[:, idx["Step"]] / 1000.0  # ps (dt = 1 fs)
    pe = a[:, idx["PotEng"]]
    T = a[:, idx["Temp"]]
    print(f"[PREEQ] {d.name}: {len(step)} thermo rows, t = 0..{step[-1]:.0f} ps")
    print(f"  {'t(ps)':>7} {'PotEng':>13} {'T':>7} {'dPE/dt':>9}")
    n = len(step)
    blk = max(1, n // 12)
    for i in range(0, n - 1, blk):
        j = min(i + blk, n - 1)
        slope = (pe[j] - pe[i]) / (step[j] - step[i]) if step[j] > step[i] else float("nan")
        print(f"  {step[i]:7.0f} {pe[i]:13.2f} {T[i]:7.1f} {slope:+9.4f}")
    cut = int((1 - args.last) * n)
    sl = np.polyfit(step[cut:], pe[cut:], 1)[0]
    last = np.polyfit(step[-max(5, n // 20):], pe[-max(5, n // 20):], 1)[0]
    print(f"  last {args.last:.0%} slope = {sl:+.4f} eV/ps ; "
          f"very-last slope = {last:+.4f} eV/ps")
    verdict = "PLATEAU (|dPE/dt| < 0.05)" if abs(last) < 0.05 else "still relaxing"
    print(f"  => {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
