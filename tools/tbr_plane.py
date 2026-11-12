#!/usr/bin/env python3
"""Interface-model-free TBR: temperature difference between two fixed planes.

Instead of extracting Kapitza jumps at assumed interface planes, take the
temperature at z = -Z and z = +Z (Z = reservoir edge, e.g. 84 A), interpolated
from the binned profile.  dT = T(-Z) - T(+Z) includes the (small) bulk
resistance, but requires no assumption about where the interfaces are or how
wide they are.  TBR_eff = dT/q.

Usage: python3 tools/tbr_plane.py --run-dir <run> --seed seed_1001 [--z 84]
"""
from __future__ import annotations

import argparse, json, math, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib


def parse_blocks(path: Path):
    blocks = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("%"):
            continue
        p = s.split()
        if len(p) == 3:
            blocks.append({"step": int(p[0]), "rows": []})
        elif len(p) == 4:
            blocks[-1]["rows"].append([float(x) for x in p])
    return blocks


def profile(bl):
    nb = len(bl[0]["rows"])
    acc = np.zeros(nb); cnt = np.zeros(nb, int)
    z = np.array([r[1] for r in bl[0]["rows"]])
    for b in bl:
        a = np.array(b["rows"]); occ = a[:, 2] > 0
        acc[occ] += a[occ, 3]; cnt[occ] += 1
    T = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    return z, T


def dT_planes(z, T, Z):
    """Linear interpolation of T at z = -Z and z = +Z using the nearest finite bins."""
    def at(zp):
        m = np.isfinite(T)
        zz, tt = z[m], T[m]
        if zp < zz.min() or zp > zz.max():
            raise ValueError(f"z={zp} outside occupied range {zz.min()}..{zz.max()}")
        i = np.searchsorted(zz, zp)
        if i == 0:
            return tt[0]
        if i >= len(zz):
            return tt[-1]
        z0, z1, t0, t1 = zz[i-1], zz[i], tt[i-1], tt[i]
        return t0 + (t1 - t0) * (zp - z0) / (z1 - z0)
    return at(-Z) - at(Z)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--z", type=float, default=84.0)
    ap.add_argument("--burn", type=float, default=0.0)
    ap.add_argument("--blocks", type=int, default=10)
    args = ap.parse_args()

    run = Path(args.run_dir).resolve()
    sd = run / args.seed
    geom = geomlib.load_json(run / "geom.json")
    params = geomlib.load_json(run / "params.snapshot.json")
    blocks = parse_blocks(sd / "profile.txt")
    n0 = int(len(blocks) * args.burn)
    use = blocks[n0:]
    z, T = profile(use)
    dT = dT_planes(z, T, args.z)
    area = float(geom["box"]["lx"]) * float(geom["box"]["ly"])
    q = (float(params["flux_ev_per_ps"]) * float(params["units"]["ev_per_ps_to_W"])
         / (area * float(params["units"]["ang2_to_m2"])))
    tbr = dT / q

    per = []
    idxs = np.linspace(n0, len(blocks), args.blocks + 1).astype(int)
    for a, b in zip(idxs[:-1], idxs[1:]):
        if b <= a:
            continue
        zb, Tb = profile(blocks[a:b])
        per.append(dT_planes(zb, Tb, args.z) / q)
    per = np.array(per)
    sem = per.std(ddof=1) / math.sqrt(len(per)) if len(per) > 1 else float("nan")
    # half-to-half
    h = len(per) // 2
    rel = abs(per[:h].mean() - per[h:].mean()) / per[h:].mean()

    print(f"{run.name}: dT(+-{args.z:.0f}) = {dT:.2f} K  "
          f"TBR_eff = {tbr:.4e} +/- {sem:.2e} ({100*sem/tbr:.1f}%)  "
          f"half-to-half = {100*rel:.1f}%")
    out = {"run_id": run.name, "seed": args.seed, "z_planes": args.z,
           "dT_K": dT, "q_W_m2": q, "TBR_eff_m2KW": tbr,
           "TBR_sem": sem, "half_to_half_rel": rel,
           "blocks_used": len(use)}
    geomlib.dump_json(sd / "tbr_planes.json", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
