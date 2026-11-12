#!/usr/bin/env python3
"""Production geometry generator: Si(001) / Ti(hcp) / Au, scheme B.

Scheme B (human decision 2026-11-10):
  * grooves are etched into the Ti side of the Au/Ti interface and filled by Au
    from the Au film;
  * t is the Au film thickness (variable);
  * Ti is described by LJ in the interface model (hcp geometry, no Ti MEAM
    multi-element set); Ti bulk can be validated separately with meam/spline;
  * pattern side: single (top Au/Ti only) or double (both Au/Ti interfaces).

Stack (z, symmetric):
  Si_L 40 A | Ti_L ti | Au t | Ti_R ti | Si_R 40 A
  interfaces: -(t/2+ti) Si/Ti, -t/2 Ti/Au, +t/2 Au/Ti, +(t/2+ti) Ti/Si

Usage:
  python tools/build_geometry.py --scan-id ANCHOR --kind flat --t-nm 4.0 \
      --ti 20 --si 40 --status APPROVED \
      --out-structure structures/ANCHOR.data --out-geom structures/ANCHOR.geom.json
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

L = 65.16
A_SI = 5.43
A_AU = 4.0725
TI_A = L / 22.0
TI_C = 4.68
SQ3 = math.sqrt(3.0)

SI_BASIS = [
    (0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
    (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25),
]
AU_BASIS = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0)]


def _grid(n: int, a: float) -> np.ndarray:
    return np.arange(n) * a


def si_block(z0: float, z1: float) -> np.ndarray:
    n = int(round(L / A_SI))
    assert abs(L - n * A_SI) < 1e-6
    g = _grid(n, A_SI)
    X, Y = np.meshgrid(g, g, indexing="xy")
    out = []
    k0 = math.floor(z0 / A_SI) - 1
    k1 = math.ceil(z1 / A_SI) + 1
    for k in range(k0, k1 + 1):
        for bx, by, bz in SI_BASIS:
            z = (k + bz) * A_SI
            if z0 - 1e-6 <= z <= z1 + 1e-6:
                out.append(np.column_stack([
                    (X + bx * A_SI).ravel() % L,
                    (Y + by * A_SI).ravel() % L,
                    np.full(X.size, z),
                ]))
    return np.vstack(out)


def au_block(z0: float, z1: float) -> np.ndarray:
    n = int(round(L / A_AU))
    assert abs(L - n * A_AU) < 1e-6
    g = _grid(n, A_AU)
    X, Y = np.meshgrid(g, g, indexing="xy")
    out = []
    k0 = math.floor(z0 / A_AU) - 1
    k1 = math.ceil(z1 / A_AU) + 1
    for k in range(k0, k1 + 1):
        for bx, by, bz in AU_BASIS:
            z = (k + bz) * A_AU
            if z0 - 1e-6 <= z <= z1 + 1e-6:
                out.append(np.column_stack([
                    (X + bx * A_AU).ravel() % L,
                    (Y + by * A_AU).ravel() % L,
                    np.full(X.size, z),
                ]))
    return np.vstack(out)


def ti_block(z0: float, z1: float) -> np.ndarray:
    """hcp Ti, rectangular basal cell a x a*sqrt(3), AB stacking along c/2.

    y is strained by <2.5% to fit the square in-plane cell; this is a geometry
    model (Ti-Ti is LJ), not a MEAM Ti crystal.
    """
    nx = int(round(L / TI_A))
    assert abs(L - nx * TI_A) < 1e-6
    y_scale = L / (13 * TI_A * SQ3)
    dz = TI_C / 2.0
    k0 = math.floor(z0 / dz) - 1
    k1 = math.ceil(z1 / dz) + 1
    gx = _grid(nx, TI_A)
    gy = _grid(13, TI_A * SQ3 * y_scale)
    X, Y = np.meshgrid(gx, gy, indexing="xy")
    out = []
    for k in range(k0, k1 + 1):
        z = k * dz
        if not (z0 - 1e-6 <= z <= z1 + 1e-6):
            continue
        sx, sy = (0.5, 1.0 / 6.0) if k % 2 else (0.0, 0.0)
        for bx, by in ((0.0, 0.0), (0.5, 0.5)):
            out.append(np.column_stack([
                (X + (bx + sx) * TI_A).ravel() % L,
                (Y + (by + sy) * TI_A * SQ3 * y_scale).ravel() % L,
                np.full(X.size, z),
            ]))
    return np.vstack(out)


def groove_depth(x: np.ndarray, y: np.ndarray, spec: dict) -> np.ndarray:
    kind = spec["kind"]
    if kind == "flat":
        return np.zeros_like(x, dtype=float)
    P, W, D = spec["P"], spec["W"], spec["D"]
    if kind == "rot45":
        ang = math.radians(45.0)
        d = np.mod(x * math.cos(ang) + y * math.sin(ang), P)
        return np.where(d < W, D, 0.0)
    if kind == "rect":
        if spec["phi"] == 0.0:
            d = np.mod(x, P)
        elif spec["phi"] == 90.0:
            d = np.mod(y, P)
        else:
            ang = math.radians(spec["phi"])
            d = np.mod(x * math.cos(ang) + y * math.sin(ang), P)
        return np.where(d < W, D, 0.0)
    if kind == "cross":
        gx = np.mod(x, P) < W
        gy = np.mod(y, P) < W
        return np.where(gx | gy, D, 0.0)
    if kind == "trapezoid":
        d = np.abs(np.mod(x, P) - P / 2.0)
        half = W / 2.0
        tan_a = math.tan(math.radians(60.0))
        return np.clip((half - d) / tan_a, 0.0, D)
    raise ValueError(f"unknown kind: {kind}")


def remove_close(frame: np.ndarray, other: np.ndarray, cutoff: float) -> np.ndarray:
    if len(other) == 0:
        return np.arange(len(frame))
    keep = np.ones(len(frame), dtype=bool)
    c2 = cutoff * cutoff
    for i in range(0, len(frame), 200):
        p = frame[i:i + 200][:, None, :]
        d = p - other[None, :, :]
        d[:, :, 0] -= L * np.round(d[:, :, 0] / L)
        d[:, :, 1] -= L * np.round(d[:, :, 1] / L)
        dist2 = np.einsum("ijk,ijk->ij", d, d)
        keep[i:i + 200] = ~(dist2 < c2).any(axis=1)
    return np.nonzero(keep)[0]


def build(spec: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    t = spec["t"]
    ti = spec["ti"]
    si = spec["si"]
    z_au = t / 2.0
    z_si_ti = z_au + ti
    z_si_out = z_si_ti + si

    si_l = si_block(-z_si_out, -z_si_ti)
    si_r = si_block(z_si_ti, z_si_out)

    ti_l = ti_block(-z_si_ti, -z_au)
    ti_r = ti_block(z_au, z_si_ti)
    if spec["sided"] == "double":
        # bottom Ti layer: etch towards -z, so keep atoms at z <= -z_au - D
        d = groove_depth(ti_l[:, 0], ti_l[:, 1], spec)
        ti_l = ti_l[ti_l[:, 2] <= -z_au - d + 1e-6]
    d = groove_depth(ti_r[:, 0], ti_r[:, 1], spec)
    ti_r = ti_r[ti_r[:, 2] >= z_au + d - 1e-6]
    ti_l = ti_l[remove_close(ti_l, si_l, 1.9)]
    ti_r = ti_r[remove_close(ti_r, si_r, 1.9)]

    au = au_block(-z_au - spec["D"] - 2.0, z_au + spec["D"] + 2.0)
    d_top = groove_depth(au[:, 0], au[:, 1], spec)
    if spec["sided"] == "double":
        d_bot = d_top
    else:
        d_bot = np.zeros_like(d_top)
    in_film = (au[:, 2] >= -z_au - 1e-6) & (au[:, 2] <= z_au + 1e-6)
    in_top = (au[:, 2] > z_au) & (au[:, 2] <= z_au + d_top + 1e-6)
    in_bot = (au[:, 2] < -z_au) & (au[:, 2] >= -z_au - d_bot - 1e-6)
    au = au[in_film | in_top | in_bot]
    au = au[remove_close(au, si_l, 1.8)]
    au = au[remove_close(au, si_r, 1.8)]
    au = au[remove_close(au, ti_l, 1.7)]
    au = au[remove_close(au, ti_r, 1.7)]

    atoms = np.vstack([si_l, ti_l, au, ti_r, si_r])
    types = np.concatenate([
        np.ones(len(si_l), dtype=int),
        np.full(len(ti_l), 2, dtype=int),
        np.full(len(au), 3, dtype=int),
        np.full(len(ti_r), 2, dtype=int),
        np.ones(len(si_r), dtype=int),
    ])
    meta = dict(t=t, ti=ti, si=si, z_au=z_au, z_si_ti=z_si_ti, z_si_out=z_si_out,
                n_si_l=len(si_l), n_ti_l=len(ti_l), n_au=len(au),
                n_ti_r=len(ti_r), n_si_r=len(si_r))
    return atoms, types, meta


def make_geom(spec: dict, meta: dict) -> dict:
    t, ti, si = spec["t"], spec["ti"], spec["si"]
    z_au, z_st, z_out = meta["z_au"], meta["z_si_ti"], meta["z_si_out"]
    D = spec["D"]
    # top Ti window sits above the deepest groove
    ti_au_lo = z_au + D + 2.0
    ti_au_hi = z_au + 18.0
    ti_au_bot_hi = -z_au - D - 2.0
    ti_au_bot_lo = -z_au - 18.0
    windows = {
        "Si_Ti_L": ([-z_st - 2.0, -z_st - 18.0], [-z_st + 2.0, -z_st + 18.0]),
        "Ti_Au_L": ([ti_au_bot_lo, ti_au_bot_hi], [-z_au + 2.0, -z_au + 18.0]),
        "Au_Ti_R": ([z_au - 18.0, z_au - 2.0], [ti_au_lo, ti_au_hi]),
        "Ti_Si_R": ([z_st - 18.0, z_st - 2.0], [z_st + 2.0, z_st + 18.0]),
    }
    return {
        "schema_version": "1.0",
        "status": spec["status"],
        "geometry_id": spec["geom_id"],
        "note": spec["note"],
        "box": {
            "lx": L, "ly": L,
            "z_min": -z_out - 15.0, "z_max": z_out + 15.0,
            "boundary": "p p p",
        },
        "layers": [
            {"id": "Si_L", "material": "Si", "z_min": -z_out, "z_max": -z_st},
            {"id": "Ti_L", "material": "Ti", "z_min": -z_st, "z_max": -z_au},
            {"id": "Au",   "material": "Au", "z_min": -z_au, "z_max": z_au},
            {"id": "Ti_R", "material": "Ti", "z_min": z_au, "z_max": z_st},
            {"id": "Si_R", "material": "Si", "z_min": z_st, "z_max": z_out},
        ],
        "interfaces": [
            {"id": "Si_Ti_L", "z": -z_st,
             "left":  {"z_min": -z_st - 18.0, "z_max": -z_st - 2.0, "material": "Si"},
             "right": {"z_min": -z_st + 2.0,  "z_max": -z_st + 18.0, "material": "Ti"}},
            {"id": "Ti_Au_L", "z": -z_au,
             "left":  {"z_min": ti_au_bot_lo, "z_max": ti_au_bot_hi, "material": "Ti"},
             "right": {"z_min": -z_au + 2.0, "z_max": -z_au + 18.0, "material": "Au"}},
            {"id": "Au_Ti_R", "z": z_au,
             "left":  {"z_min": z_au - 18.0, "z_max": z_au - 2.0, "material": "Au"},
             "right": {"z_min": ti_au_lo, "z_max": ti_au_hi, "material": "Ti"}},
            {"id": "Ti_Si_R", "z": z_st,
             "left":  {"z_min": z_st - 18.0, "z_max": z_st - 2.0, "material": "Ti"},
             "right": {"z_min": z_st + 2.0,  "z_max": z_st + 18.0, "material": "Si"}},
        ],
        "groups": {
            # reservoir inset: keep the thermostat away from the free surface,
            # otherwise the surface relaxation transient (hundreds of K) dominates
            # the imposed flux and the profile is not linear (protocol v1.2).
            "hot":  {"z_min": -z_out + spec["res_inset"],
                     "z_max": -z_out + spec["res_inset"] + 8.0},
            "cold": {"z_min": z_out - spec["res_inset"] - 8.0,
                     "z_max": z_out - spec["res_inset"]},
        },
        "chunk_bin_A": spec["bin"],
    }


def write_data(path: Path, atoms: np.ndarray, types: np.ndarray, z_min: float, z_max: float) -> None:
    lines = [
        "LAMMPS data file: Si(001)/Ti(hcp)/Au/Ti/Si production geometry",
        "",
        f"{len(atoms)} atoms",
        "3 atom types",
        "",
        f"0.0 {L:.6f} xlo xhi",
        f"0.0 {L:.6f} ylo yhi",
        f"{z_min:.6f} {z_max:.6f} zlo zhi",
        "",
        "Masses", "", "1 28.0855", "2 47.867", "3 196.96657", "",
        "Atoms # atomic", "",
    ]
    for i, ((x, y, z), ty) in enumerate(zip(atoms, types), 1):
        lines.append(f"{i} {ty} {x:.6f} {y:.6f} {z:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-id", required=True)
    ap.add_argument("--kind", default="flat",
                    choices=["flat", "rect", "trapezoid", "cross", "rot45"])
    ap.add_argument("--t-nm", type=float, default=4.0, help="Au film thickness")
    ap.add_argument("--ti", type=float, default=24.0, help="Ti thickness (A)")
    ap.add_argument("--si", type=float, default=40.0, help="Si thickness (A)")
    ap.add_argument("--W-nm", type=float, default=0.0)
    ap.add_argument("--D-nm", type=float, default=0.0)
    ap.add_argument("--P-nm", type=float, default=0.0)
    ap.add_argument("--phi", type=float, default=0.0)
    ap.add_argument("--sided", default="single", choices=["single", "double"])
    ap.add_argument("--bin", type=float, default=2.0)
    ap.add_argument("--res-inset", type=float, default=0.0,
                    help="A: hot/cold reservoirs inset from the free surfaces (protocol v1.2)")
    ap.add_argument("--status", default="DRAFT", choices=["DRAFT", "APPROVED"])
    ap.add_argument("--out-structure", required=True)
    ap.add_argument("--out-geom", required=True)
    args = ap.parse_args()

    spec = {
        "scan_id": args.scan_id,
        "geom_id": f"{args.scan_id}_{args.kind}",
        "kind": args.kind,
        "t": args.t_nm * 10.0,
        "ti": args.ti,
        "si": args.si,
        "W": args.W_nm * 10.0,
        "D": args.D_nm * 10.0,
        "P": args.P_nm * 10.0,
        "phi": args.phi,
        "sided": args.sided,
        "bin": args.bin,
        "res_inset": args.res_inset,
        "status": args.status,
        "note": (f"{args.scan_id}: Si(001)/Ti(hcp)/Au/Ti/Si, scheme B "
                 f"(etch Ti, fill Au); t(Au)={args.t_nm} nm, Ti={args.ti} A, "
                 f"W={args.W_nm} nm, D={args.D_nm} nm, P={args.P_nm} nm, "
                 f"phi={args.phi} deg, {args.sided}"),
    }
    if spec["kind"] != "flat":
        if not (spec["P"] > spec["W"] > 0 and 0 < spec["D"] <= 8.0):
            print("[GEOM][FAIL] 需要 P>W>0 且 0<D<=8 A（T=24 A 时）", file=sys.stderr)
            return 2

    atoms, types, meta = build(spec)
    geom = make_geom(spec, meta)

    out_s = Path(args.out_structure)
    out_g = Path(args.out_geom)
    out_s.parent.mkdir(parents=True, exist_ok=True)
    out_g.parent.mkdir(parents=True, exist_ok=True)
    write_data(out_s, atoms, types, geom["box"]["z_min"], geom["box"]["z_max"])
    geomlib.dump_json(out_g, geom)

    rep = geomlib.validate_geom(geom, {"fit_window_min_A": 6.0, "fit_min_points": 4},
                                allow_draft=True, bin_a=spec["bin"])
    print(f"[GEOM] {out_s}  atoms={len(atoms)}  Si={int((types==1).sum())} "
          f"Ti={int((types==2).sum())} Au={int((types==3).sum())}")
    print(f"[GEOM] {out_g}  status={geom['status']}  bin={spec['bin']} "
          f"res_inset={spec['res_inset']} A  hot={geom['groups']['hot']} cold={geom['groups']['cold']}")
    if rep["errors"]:
        for e in rep["errors"]:
            print("  -", e)
        return 2
    print("[GEOM] geometry validation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
