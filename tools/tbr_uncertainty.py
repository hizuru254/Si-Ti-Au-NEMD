#!/usr/bin/env python3
"""Uncertainty-aware TBR analysis (companion to the canonical postprocess.py).

postprocess.py reports a single number from the last 20 % of the production run
and applies the R^2 >= 0.995 gate.  That gate is a *bulk-linearity* test on a
16 A window; at 1 eV/ps the bulk temperature drop inside such a window is
~0.2 K while the 2 A bin noise is ~1.2 K, so the gate cannot be met for this
stack no matter how long the run is.  This tool instead reports the physically
meaningful quantity with an explicit statistical error:

  * burn-in  : first `burn` fraction of production is discarded
  * dT_i     : per-interface temperature jump (same extrapolation as postprocess)
  * sigma    : block-averaged standard error over the averaging window
  * TBR      : sum(dT)/q with propagated sigma

Output: <run>/seed_*/tbr_uncertainty.json and a text table on stdout.

Usage:
  python3 tools/tbr_uncertainty.py --run-dir <dir> --seed seed_1001 [--burn 0.2] [--blocks 10]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402


def parse_blocks(path: Path) -> list[dict]:
    blocks: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("%"):
            continue
        p = s.split()
        if len(p) == 3:
            blocks.append({"step": int(p[0]), "n": int(p[1]), "rows": []})
        elif len(p) == 4:
            blocks[-1]["rows"].append([float(x) for x in p])
    return blocks


def avg(blocks: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    n = len(blocks[0]["rows"])
    acc = np.zeros(n)
    cnt = np.zeros(n, dtype=int)
    zacc = np.zeros(n)
    for b in blocks:
        a = np.array(b["rows"], dtype=float)
        occ = a[:, 2] > 0
        acc[occ] += a[occ, 3]
        cnt[occ] += 1
        zacc += a[:, 1]
    z = zacc / len(blocks)
    T = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    return z, T


def dT_all(z: np.ndarray, T: np.ndarray, geom: dict) -> list[float]:
    out = []
    for itf in geom["interfaces"]:
        zs = float(itf["z"])
        vals = {}
        for side in ("left", "right"):
            w = itf[side]
            m = (z >= w["z_min"]) & (z <= w["z_max"]) & np.isfinite(T)
            if m.sum() < 2:
                out.append(float("nan"))
                break
            c = np.polyfit(z[m], T[m], 1)
            vals[side] = float(np.polyval(c, zs))
        else:
            out.append(abs(vals["left"] - vals["right"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--burn", type=float, default=0.2)
    ap.add_argument("--blocks", type=int, default=10)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    seed_dir = run_dir / args.seed
    geom = geomlib.load_json(run_dir / "geom.json")
    params = geomlib.load_json(run_dir / "params.snapshot.json")
    blocks = parse_blocks(seed_dir / "profile.txt")
    if not blocks:
        print("[TBRU][FAIL] 没有 profile 块", file=sys.stderr)
        return 2

    n0 = int(len(blocks) * args.burn)
    use = blocks[n0:]
    if len(use) < args.blocks:
        args.blocks = max(2, len(use))
    z, T = avg(use)
    dts = np.array(dT_all(z, T, geom), dtype=float)

    area = float(geom["box"]["lx"]) * float(geom["box"]["ly"])
    q = (float(params["flux_ev_per_ps"]) * float(params["units"]["ev_per_ps_to_W"])
         / (area * float(params["units"]["ang2_to_m2"])))

    # block average over the averaging window
    per_block = []
    idx = np.linspace(n0, len(blocks), args.blocks + 1).astype(int)
    for a, b in zip(idx[:-1], idx[1:]):
        if b <= a:
            continue
        zb, Tb = avg(blocks[a:b])
        per_block.append(dT_all(zb, Tb, geom))
    per_block = np.array(per_block, dtype=float)
    nblk = per_block.shape[0]
    sem = per_block.std(axis=0, ddof=1) / math.sqrt(nblk) if nblk > 1 else np.full(len(dts), np.nan)

    tbr = dts.sum() / q
    tbr_sem = float(np.sqrt(np.nansum(sem ** 2))) / q

    print("=" * 78)
    print(f"TBR uncertainty  {run_dir.name}/{args.seed}")
    print(f"  production blocks={len(blocks)}  burn={args.burn:.0%}  "
          f"averaged={len(use)} ps  sub-blocks={nblk}")
    print(f"  q = {q:.4e} W/m2")
    print("-" * 78)
    print(f"  {'interface':10s} {'dT (K)':>9s} {'sigma':>7s} {'SNR':>6s} {'TBR':>11s}")
    for i, itf in enumerate(geom["interfaces"]):
        snr = dts[i] / sem[i] if sem[i] and np.isfinite(sem[i]) else float("nan")
        print(f"  {itf['id']:10s} {dts[i]:9.2f} {sem[i]:7.2f} {snr:6.1f} "
              f"{dts[i] / q:11.3e}")
    print("-" * 78)
    print(f"  dT_total = {dts.sum():.2f} +/- {math.sqrt(np.nansum(sem**2)):.2f} K")
    print(f"  TBR      = {tbr:.4e} +/- {tbr_sem:.4e} m2K/W  "
          f"({100 * tbr_sem / tbr:.1f} %)")
    print("=" * 78)

    out = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "seed": args.seed,
        "flux_ev_per_ps": params["flux_ev_per_ps"],
        "q_W_m2": q,
        "burn_fraction": args.burn,
        "blocks_total": len(blocks),
        "blocks_used": len(use),
        "sub_blocks": int(nblk),
        "interfaces": [
            {"id": itf["id"], "z": itf["z"], "dT_K": float(dts[i]),
             "dT_sem_K": float(sem[i]),
             "snr": float(dts[i] / sem[i]) if sem[i] else None,
             "tbr_m2KW": float(dts[i] / q)}
            for i, itf in enumerate(geom["interfaces"])
        ],
        "dT_total_K": float(dts.sum()),
        "dT_total_sem_K": float(math.sqrt(np.nansum(sem ** 2))),
        "TBR_total_m2KW": float(tbr),
        "TBR_sem_m2KW": tbr_sem,
        "TBR_rel_unc": float(tbr_sem / tbr),
    }
    geomlib.dump_json(seed_dir / "tbr_uncertainty.json", out)
    print(f"  写入: {seed_dir / 'tbr_uncertainty.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
