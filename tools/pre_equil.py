#!/usr/bin/env python3
"""Long pre-equilibration to a potential-energy plateau (protocol v1.4 step 1).

Runs the structure under regional NVT (two halves, 300 K) for --steps, writing a
checkpoint every --chunk steps so the drift dPE/dt can be monitored and the run
resumed/stopped without losing work.

Usage:
  python3 tools/pre_equil.py --structure structures/F000.data \
      --geom structures/F000.geom.json --potentials anchor/potentials.in \
      --out-dir preeq/F000 --steps 600000 --chunk 100000 --temp 300
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structure", required=True)
    ap.add_argument("--geom", required=True)
    ap.add_argument("--potentials", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--steps", type=int, default=600000)
    ap.add_argument("--chunk", type=int, default=100000)
    ap.add_argument("--temp", type=float, default=300.0)
    ap.add_argument("--seed", type=int, default=1001)
    ap.add_argument("--dt", type=float, default=0.001)
    ap.add_argument("--run", action="store_true", help="actually launch LAMMPS")
    ap.add_argument("--mpi", type=int, default=0, help="mpirun -np N (0 = serial)")
    ap.add_argument("--anneal-temp", type=float, default=0.0,
                    help="if >0: ramp 300 -> T -> 300 before the 300 K hold")
    ap.add_argument("--anneal-up", type=int, default=20000)
    ap.add_argument("--anneal-hold", type=int, default=30000)
    ap.add_argument("--anneal-down", type=int, default=30000)
    args = ap.parse_args()

    geom = geomlib.load_json(Path(args.geom))
    g = geom["groups"]
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    struct = Path(args.structure).resolve()

    chunks = [args.chunk] * (args.steps // args.chunk)
    if args.steps % args.chunk:
        chunks.append(args.steps % args.chunk)

    lines = [
        "# pre-equilibration (protocol v1.4): regional NVT, no heat flux",
        "units metal",
        "atom_style atomic",
        "boundary p p p",
        f"read_data {struct}",
        f"include {Path(args.potentials).resolve()}",
        "neighbor 2.0 bin",
        "neigh_modify delay 0 every 1 check yes",
        "min_style cg",
        "min_modify dmax 0.05",
        "minimize 1e-6 1e-8 10000 100000",
        f"velocity all create {args.temp} {args.seed} dist gaussian mom yes rot yes",
        "variable zmid equal 0.5*(zlo+zhi)",
        "region halfL block INF INF INF INF -100000.0 ${zmid} units box",
        "region halfR block INF INF INF INF ${zmid} 100000.0 units box",
        "group halfL_g region halfL",
        "group halfR_g region halfR",
        f"fix eqL halfL_g nvt temp {args.temp} {args.temp} 0.1",
        f"fix eqR halfR_g nvt temp {args.temp} {args.temp} 0.1",
        f"timestep {args.dt}",
        "thermo 1000",
        "thermo_style custom step temp pe ke etotal",
        "thermo_modify flush yes",
    ]
    done = 0
    if args.anneal_temp > 0:
        ta = args.anneal_temp
        stages = [("ramp-up", 300.0, ta, args.anneal_up),
                  ("hold", ta, ta, args.anneal_hold),
                  ("ramp-down", ta, 300.0, args.anneal_down)]
        for name, t0, t1, n in stages:
            lines.append(f'print "ANNEAL {name} {t0}->{t1} steps={n}"')
            lines.append(f"unfix eqL")
            lines.append(f"unfix eqR")
            lines.append(f"fix eqL halfL_g nvt temp {t0} {t1} 0.1")
            lines.append(f"fix eqR halfR_g nvt temp {t0} {t1} 0.1")
            lines.append(f"run {n}")
            done += n
            lines.append(f'print "PREEQ_CHECKPOINT step={done} stage={name}"')
            lines.append(f"write_data {out}/preeq_{done:07d}.data")
        lines.append(f"print \"ANNEAL done, settle at 300 K\"")
        lines.append("unfix eqL")
        lines.append("unfix eqR")
        lines.append("fix eqL halfL_g nvt temp 300.0 300.0 0.1")
        lines.append("fix eqR halfR_g nvt temp 300.0 300.0 0.1")
    for i, n in enumerate(chunks, 1):
        lines.append(f"run {n}")
        done += n
        lines.append(f'print "PREEQ_CHECKPOINT step={done}"')
        lines.append(f"write_data {out}/preeq_{done:07d}.data")
    (out / "in.preeq").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"[PREEQ] input: {out / 'in.preeq'}  steps={args.steps} chunks={chunks[:3]}...")
    if not args.run:
        print("[PREEQ] dry (pass --run to launch)")
        return 0
    cmd = ([f"mpirun", "-np", str(args.mpi), "--bind-to", "core",
            "/usr/bin/lmp"] if args.mpi else ["/usr/bin/lmp"])
    cmd += ["-in", "in.preeq", "-log", "log.preeq"]
    print("[PREEQ] " + " ".join(cmd))
    rc = subprocess.run(cmd, cwd=str(out)).returncode
    print(f"[PREEQ] exit={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
