#!/usr/bin/env python3
"""Validation-only structure builder: Si/Ti/Au/Ti/Si layered stack (symmetric).

Purpose: exercise the *pipeline* (3 atom types, real potential files, layered
geometry, multiple interfaces) on this machine.  It is NOT the production
geometry generator and the resulting structure is NOT a publication-quality
Si/Ti/Au interface:

  * Si is diamond (a = 5.43 A), Au is fcc (a = 4.0725 A), Ti is fcc + LJ
    (no Ti multi-element MEAM set exists locally).
  * In-plane 16.29 A is commensurate with 4 x 4.0725 and 3 x 5.43.
  * Each layer is centred in its geometric span so interfaces are symmetric
    and no atom pair is initially overlapping.
  * Cross-layer interactions are LJ; only Si-Si (Tersoff) and Au-Au (EAM) are
    many-body.
  * Order: Si(substrate)/Ti/Au/Ti/Si(substrate), i.e. an Au film with Ti
    adhesion on a Si substrate, mirrored for periodic NEMD.

Usage: python tools/build_stack_validation.py --geom validation/geom.json --out validation/structure.data
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402

FCC = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0)]
DIA = FCC + [(.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25)]

MATS = {
    "Si": {"lattice": "diamond", "a": 5.43, "basis": DIA, "type": 1, "mass": 28.0855},
    "Ti": {"lattice": "fcc", "a": 4.0725, "basis": FCC, "type": 2, "mass": 47.867},
    "Au": {"lattice": "fcc", "a": 4.0725, "basis": FCC, "type": 3, "mass": 196.96657},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--inset", type=float, default=1.5)
    args = ap.parse_args()

    geom = geomlib.load_json(Path(args.geom))
    lx = float(geom["box"]["lx"])
    ly = float(geom["box"]["ly"])
    zmin = float(geom["box"]["z_min"])
    zmax = float(geom["box"]["z_max"])

    atoms = []
    report = []
    for layer in geom["layers"]:
        mat = layer["material"]
        spec = MATS[mat]
        a = spec["a"]
        z0, z1 = float(layer["z_min"]), float(layer["z_max"])
        thickness = z1 - z0
        nx, ny = round(lx / a), round(ly / a)
        if abs(lx - nx * a) > 1e-6 or abs(ly - ny * a) > 1e-6:
            print(f"[BUILD][FAIL] {layer['id']}: lx/ly 与 {mat} a={a} 不匹配", file=sys.stderr)
            return 2
        nzmax = math.floor((thickness - 2 * args.inset) / a) + 1
        max_bz = max(b[2] for b in spec["basis"])
        while nzmax > 1 and (nzmax - 1 + max_bz) * a > thickness:
            nzmax -= 1
        span = (nzmax - 1 + max_bz) * a
        offset = (thickness - span) / 2.0
        count = 0
        for i in range(nx):
            for j in range(ny):
                for k in range(nzmax):
                    for bx, by, bz in spec["basis"]:
                        z = z0 + offset + (k + bz) * a
                        if z > z1 + 1e-6:
                            continue
                        atoms.append(((i + bx) * a, (j + by) * a, z, spec["type"]))
                        count += 1
        report.append((layer["id"], mat, count, z0 + offset, span))

    # minimum image in x/y for a sanity check between atoms of different layers
    import numpy as np
    arr = np.array([(x, y, z) for x, y, z, _ in atoms])
    zs = arr[:, 2]
    # only check pairs within 4 A in z (interfaces) using a coarse loop
    order = np.argsort(zs)
    sorted_z = zs[order]
    close = 0
    for i in range(len(order)):
        j = i + 1
        while j < len(order) and sorted_z[j] - sorted_z[i] < 4.0:
            p, q = arr[order[i]], arr[order[j]]
            dx = abs(p[0] - q[0]); dx = min(dx, lx - dx)
            dy = abs(p[1] - q[1]); dy = min(dy, ly - dy)
            if dx * dx + dy * dy + (p[2] - q[2]) ** 2 < 1.6 ** 2:
                close += 1
            j += 1
    if close:
        print(f"[BUILD][FAIL] 存在 {close} 对原子间距 < 1.6 A", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["LAMMPS data file: validation Au/Ti/Si/Ti/Au (fcc-Ti approximation)", "",
             f"{len(atoms)} atoms", "3 atom types", "",
             f"0.0 {lx:.6f} xlo xhi",
             f"0.0 {ly:.6f} ylo yhi",
             f"{zmin:.6f} {zmax:.6f} zlo zhi", "",
             "Masses", "", "1 28.0855", "2 47.867", "3 196.96657", "",
             "Atoms # atomic", ""]
    for idx, (x, y, z, t) in enumerate(atoms, 1):
        lines.append(f"{idx} {t} {x:.6f} {y:.6f} {z:.6f}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[BUILD] {out}  atoms={len(atoms)}")
    for lid, mat, c, first, last_guess in report:
        print(f"  {lid:<6} {mat:<3} atoms={c:<5} first_z={first:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
