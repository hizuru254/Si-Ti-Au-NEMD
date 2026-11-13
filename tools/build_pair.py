#!/usr/bin/env python3
"""Two-layer (single-interface) cell builder: Si/Ti or Ti/Au.

Rationale (see docs/BOOTSTRAP... / 建议): one interface per cell removes the
interference between the four interfaces of the 5-layer stack, lets both sides
be thick (>=60 A) and gives a clean two-plateau dT with no extrapolation.

Usage: python3 tools/build_pair.py --pair ti-au --thick 60 --bin 2 \
         --out-structure structures/PAIR_TiAu.data --out-geom structures/PAIR_TiAu.geom.json
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib
from build_geometry import L, si_block, au_block, ti_block, write_data, remove_close


def _groups(atoms, types, T, inset, tlo, thi):
    """Pick hot/cold windows (inside each slab) whose atom counts match best."""
    z = atoms[:, 2]
    best = None
    for kh in range(60, 200, 2):          # hot thickness 6.0 .. 20.0 A
        th_h = kh / 10.0
        h_lo, h_hi = -T + inset - th_h, -T + inset
        n_hot = int(((types == tlo) & (z >= h_lo) & (z <= h_hi)).sum())
        if n_hot == 0:
            continue
        for kc in range(60, 200, 2):
            th_c = kc / 10.0
            c_lo, c_hi = T - inset, T - inset + th_c
            n_cold = int(((types == thi) & (z >= c_lo) & (z <= c_hi)).sum())
            if n_cold == 0:
                continue
            score = abs(n_hot - n_cold) / max(n_hot, n_cold)
            if best is None or score < best[0]:
                best = (score, n_hot, n_cold, h_lo, h_hi, c_lo, c_hi)
    score, n_hot, n_cold, h_lo, h_hi, c_lo, c_hi = best
    print(f"[PAIR] best group match: hot={n_hot} cold={n_cold} "
          f"(diff {100*score:.1f}%) hot {h_lo:.1f}..{h_hi:.1f} cold {c_lo:.1f}..{c_hi:.1f}")
    return {"hot": {"z_min": h_lo, "z_max": h_hi},
            "cold": {"z_min": c_lo, "z_max": c_hi}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True, choices=["si-ti", "ti-au"])
    ap.add_argument("--thick", type=float, default=60.0, help="thickness of each slab (A)")
    ap.add_argument("--bin", type=float, default=2.0)
    ap.add_argument("--res-inset", type=float, default=10.0)
    ap.add_argument("--status", default="APPROVED", choices=["DRAFT", "APPROVED"])
    ap.add_argument("--out-structure", required=True)
    ap.add_argument("--out-geom", required=True)
    a = ap.parse_args()

    low, high = a.pair.split("-")       # low is the -z side, high the +z side
    T = a.thick
    builders = {"si": si_block, "ti": ti_block, "au": au_block}
    lo = builders[low](-T, 0.0)
    hi = builders[high](0.0, T)
    hi = hi[remove_close(hi, lo, 1.8)]   # no overlapping pairs at the interface
    atoms = np.vstack([lo, hi])
    tmap = {"si": 1, "ti": 2, "au": 3}
    types = np.concatenate([np.full(len(lo), tmap[low], dtype=int),
                            np.full(len(hi), tmap[high], dtype=int)])
    zin, zout = T, T + 15.0
    geom = {
        "schema_version": "1.0", "status": a.status,
        "geometry_id": f"PAIR_{low}_{high}_t{int(T)}",
        "note": f"two-layer single-interface cell {low}/{high}, {T} A each side",
        "box": {"lx": L, "ly": L, "z_min": -zout, "z_max": zout, "boundary": "p p p"},
        "layers": [
            {"id": f"{low.upper()}_L", "material": low.capitalize(), "z_min": -T, "z_max": 0.0},
            {"id": f"{high.upper()}_R", "material": high.capitalize(), "z_min": 0.0, "z_max": T},
        ],
        "interfaces": [{
            "id": f"{low.upper()}_{high.upper()}", "z": 0.0,
            "left":  {"z_min": -16.0, "z_max": -2.0, "material": low.capitalize()},
            "right": {"z_min": 2.0, "z_max": 16.0, "material": high.capitalize()},
        }],
        "groups": _groups(atoms, types, T, a.res_inset, tmap[low], tmap[high]),
        "chunk_bin_A": a.bin,
        "expected_atoms": {"total": int(len(atoms))},
    }
    Path(a.out_structure).parent.mkdir(parents=True, exist_ok=True)
    write_data(Path(a.out_structure), atoms, types, geom["box"]["z_min"], geom["box"]["z_max"])
    geomlib.dump_json(Path(a.out_geom), geom)
    print(f"[PAIR] {a.pair} atoms={len(atoms)} "
          f"({low}:{len(lo)}, {high}:{len(hi)}) box z={geom['box']['z_min']}..{geom['box']['z_max']}")
    print(f"[PAIR] hot={geom['groups']['hot']} cold={geom['groups']['cold']}")
    return 0
if __name__ == "__main__":
    sys.exit(main())
