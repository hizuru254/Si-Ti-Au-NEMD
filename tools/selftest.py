#!/usr/bin/env python3
"""End-to-end toolchain rehearsal on a disposable Cu system.

This proves the mechanics (template rendering, LAMMPS launch, log/profile
parsing, gates, CSV) -- it does NOT validate physics or the Si/Ti/Au model.
Exit 0 only if every stage runs and the parser produces a result.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402
import new_run  # noqa: E402

A = 3.615
NX = NY = 4
NZ = 12


def _cu_eam() -> str:
    for c in ("/usr/share/lammps/potentials/Cu_u3.eam",
              "/home/cc/lammps/potentials/Cu_u3.eam"):
        if Path(c).exists():
            return c
    raise SystemExit("Cu_u3.eam not found; edit _cu_eam() in tools/selftest.py")


def write_cu_data(path: Path) -> None:
    basis = [(0, 0, 0), (0.5, 0.5, 0), (0.5, 0, 0.5), (0, 0.5, 0.5)]
    atoms = []
    for i in range(NX):
        for j in range(NY):
            for k in range(NZ):
                for bx, by, bz in basis:
                    atoms.append(((i + bx) * A, (j + by) * A, (k + bz) * A))
    lines = ["LAMMPS data file: selftest Cu", "",
             f"{len(atoms)} atoms", "1 atom types", "",
             f"0.0 {NX * A:.6f} xlo xhi",
             f"0.0 {NY * A:.6f} ylo yhi",
             f"0.0 {NZ * A + 12.0:.6f} zlo zhi", "",
             "Masses", "", "1 63.546", "", "Atoms # atomic", ""]
    for idx, (x, y, z) in enumerate(atoms, 1):
        lines.append(f"{idx} 1 {x:.6f} {y:.6f} {z:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    tools = Path(__file__).resolve().parent
    base_cfg = tools.parent / "config" / "params.json"
    base = geomlib.load_json(base_cfg)

    examples = tools.parent / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    work = examples / f"selftest_{int(time.time())}_{os.getpid()}"
    work.mkdir(parents=False, exist_ok=False)
    run_dir = work / "run_v001"
    print(f"[SELFTEST] work dir: {work}")

    params = json.loads(json.dumps(base))
    params["project_root"] = "."
    params["run"].update({"n_equil_steps": 500, "n_prod_steps": 2000,
                          "thermo_every": 50, "chunk_bin_A": 2.0,
                          "ave_nevery": 5, "ave_nrepeat": 20, "ave_nfreq": 100})
    params["thresholds"].update({
        "dT_total_min_K": 0.0,
        "fit_r2_min": 0.0,
        "tbr_min_m2KW": 0.0,
        "tbr_relstd_max": 10.0,
        "time_convergence_max_rel": 10.0,
        "temp_stability_max_K": 200.0,
    })
    params["lammps"]["launch_mode"] = "serial"

    write_cu_data(work / "structure.data")
    (work / "potentials.in").write_text(
        'pair_style eam\n'
        'pair_coeff * * "' + _cu_eam() + '"\n',
        encoding="utf-8")
    (work / "config").mkdir(parents=True, exist_ok=True)
    geomlib.dump_json(work / "config" / "potentials.lock.json", {
        "schema_version": "1.0",
        "status": "APPROVED",
        "files": {"potentials.in": {"sha256": geomlib.sha256_file(work / "potentials.in"),
                                    "note": "selftest Cu EAM"}},
        "bulk_validation": {"verdict": "PASS", "note": "selftest only"},
    })

    geom = {
        "schema_version": "1.0",
        "status": "APPROVED",
        "geometry_id": "selftest_cu",
        "box": {"lx": NX * A, "ly": NY * A, "z_min": 0.0, "z_max": NZ * A + 12.0,
                "boundary": "p p p"},
        "layers": [
            {"id": "Cu_L", "material": "Cu", "z_min": 0.0, "z_max": 21.69},
            {"id": "Cu_R", "material": "Cu", "z_min": 21.69, "z_max": NZ * A},
        ],
        "interfaces": [{
            "id": "virtual", "z": 21.69,
            "left": {"z_min": 12.0, "z_max": 20.0, "material": "Cu"},
            "right": {"z_min": 23.0, "z_max": 31.0, "material": "Cu"},
        }],
        "groups": {"hot": {"z_min": 0.0, "z_max": 10.0},
                   "cold": {"z_min": 32.5, "z_max": 42.5}},
    }
    geomlib.dump_json(work / "geom.json", geom)
    geomlib.dump_json(work / "params.snapshot.json", params)
    (work / "scan.csv").write_text(
        "scan_id,W_nm,D_nm,P_nm,t_nm,phi_deg,sided,status,note\n"
        "S000,0,0,0,0,0,single,pending,selftest\n", encoding="utf-8")

    # --- create run skeleton -------------------------------------------------
    run_dir.mkdir(parents=True)
    shutil.copy2(work / "structure.data", run_dir / "structure.data")
    shutil.copy2(work / "potentials.in", run_dir / "potentials.in")
    shutil.copy2(work / "geom.json", run_dir / "geom.json")
    shutil.copy2(work / "params.snapshot.json", run_dir / "params.snapshot.json")
    template = (tools.parent / "templates" / "in.pattern.template").read_text(encoding="utf-8")

    run_cfg = params["run"]
    values = {
        "__STRUCTURE__": "../structure.data",
        "__HOT_ZLO__": f"{geom['groups']['hot']['z_min']:.6f}",
        "__HOT_ZHI__": f"{geom['groups']['hot']['z_max']:.6f}",
        "__COLD_ZLO__": f"{geom['groups']['cold']['z_min']:.6f}",
        "__COLD_ZHI__": f"{geom['groups']['cold']['z_max']:.6f}",
        "__T_EQ__": "300.0",
        "__DT__": f"{run_cfg['timestep_ps']:.6g}",
        "__N_EQUIL__": str(run_cfg["n_equil_steps"]),
        "__N_PROD__": str(run_cfg["n_prod_steps"]),
        "__THERMO__": str(run_cfg["thermo_every"]),
        "__BIN__": f"{run_cfg['chunk_bin_A']:.6g}",
        "__AVE_NEVERY__": str(run_cfg["ave_nevery"]),
        "__AVE_NREPEAT__": str(run_cfg["ave_nrepeat"]),
        "__AVE_NFREQ__": str(run_cfg["ave_nfreq"]),
        "__FLUX__": f"{params['flux_ev_per_ps']:.10g}",
    }

    seed_dirs = []
    for seed in params["seeds"]:
        sd = run_dir / f"seed_{seed}"
        sd.mkdir()
        vals = dict(values)
        vals["__SEED__"] = str(seed)
        (sd / "in.pattern").write_text(new_run.render(template, vals, f"seed_{seed}"),
                                       encoding="utf-8", newline="\n")
        seed_dirs.append(sd)

    meta = {"schema_version": "1.0", "run_id": "run_v001",
            "scan": {"scan_id": "S000", "W_nm": "0", "D_nm": "0", "P_nm": "0",
                     "t_nm": "0", "phi_deg": "0", "sided": "single"},
            "geometry": {"geometry_id": "selftest_cu", "status": "APPROVED",
                         "sha256": geomlib.sha256_file(work / "geom.json")},
            "inputs": {"params": {"sha256": geomlib.sha256_file(work / "params.snapshot.json")}},
            "seeds": params["seeds"], "launch_mode": "serial", "state": "CREATED"}
    geomlib.dump_json(run_dir / "run_meta.json", meta)

    manifest = []
    skip = {"manifest.sha256", "README.txt", "run_meta.json"}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name not in skip:
            manifest.append(f"{geomlib.sha256_file(path)}  {path.relative_to(run_dir).as_posix()}")
    (run_dir / "manifest.sha256").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    # --- run seeds -----------------------------------------------------------
    exe = base["lammps"]["exe"]
    failures = []
    for sd in seed_dirs:
        t0 = time.time()
        proc = subprocess.run([exe, "-in", "in.pattern", "-log", "log.pattern"],
                              cwd=str(sd), capture_output=True, text=True,
                              errors="replace", timeout=600)
        wall = time.time() - t0
        geomlib.dump_json(sd / "run_meta.json",
                          {"exit_code": proc.returncode, "wall_time_s": round(wall, 2)})
        print(f"[SELFTEST] {sd.name}: exit={proc.returncode} wall={wall:.1f}s")
        if proc.returncode != 0:
            failures.append((sd.name, proc.stdout[-2000:], proc.stderr[-2000:]))

    for sd in seed_dirs:
        r = subprocess.run([sys.executable, str(tools / "postprocess.py"),
                            "--run-dir", str(run_dir), "--seed", sd.name],
                           capture_output=True, text=True, errors="replace")
        print(r.stdout.strip())
        if r.returncode != 0:
            print(r.stderr.strip())
            failures.append((f"postprocess:{sd.name}", r.stdout, r.stderr))

    r = subprocess.run([sys.executable, str(tools / "qc_check.py"), "--run-dir", str(run_dir)],
                       capture_output=True, text=True, errors="replace")
    print(r.stdout.strip())
    if r.returncode not in (0, 3):
        print(r.stderr.strip())
        failures.append(("qc_check", r.stdout, r.stderr))

    qc_path = run_dir / "qc.json"
    print("-" * 70)
    if not qc_path.exists():
        print("[SELFTEST] FAIL: qc.json 未生成")
        return 1
    qc = geomlib.load_json(qc_path)
    print(f"[SELFTEST] qc: n_valid={qc['n_valid']} is_passed={qc['is_passed']} note={qc['note']}")
    print(f"[SELFTEST] artifacts: {work}")
    if failures:
        for name, out, err in failures:
            print(f"[SELFTEST] FAILED {name}\n{out}\n{err}")
        return 1
    if qc["n_valid"] != len(params["seeds"]):
        print("[SELFTEST] FAIL: 有效种子数不足，解析或运行失败")
        return 1
    print("[SELFTEST] PASS: 工具链可执行（物理判据未验证）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
