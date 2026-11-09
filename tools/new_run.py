#!/usr/bin/env python3
"""Create an immutable run_vNNN directory and instantiate its seed inputs.

Guarantees:
  * never overwrites an existing run directory (atomic temp-dir + rename)
  * every input is hashed into manifest.sha256
  * no physics is invented here: geometry, structure and potentials are inputs
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402

RUN_RE = re.compile(r"^run_v(\d{3})$")
REQUIRED_TOKENS = {
    "__STRUCTURE__",
    "__HOT_ZLO__",
    "__HOT_ZHI__",
    "__COLD_ZLO__",
    "__COLD_ZHI__",
    "__SEED__",
    "__T_EQ__",
    "__DT__",
    "__N_EQUIL__",
    "__N_PROD__",
    "__THERMO__",
    "__BIN__",
    "__AVE_NEVERY__",
    "__AVE_NREPEAT__",
    "__AVE_NFREQ__",
    "__FLUX__",
}


def fail(msg: str, code: int = 2) -> "NoReturn":
    print(f"[NEW_RUN][FAIL] {msg}", file=sys.stderr)
    sys.exit(code)


def read_scan_row(scan_csv: Path, scan_id: str) -> dict:
    with open(scan_csv, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row.get("scan_id", "").strip() == scan_id:
            return {k: (v or "").strip() for k, v in row.items()}
    fail(f"scan.csv 中找不到 scan_id={scan_id}")


def next_run_id(workspace: Path) -> str:
    ids = []
    if workspace.exists():
        for child in workspace.iterdir():
            m = RUN_RE.match(child.name)
            if m and child.is_dir():
                ids.append(int(m.group(1)))
    nxt = max(ids) + 1 if ids else 1
    if nxt > 999:
        fail("版本号超过 999，必须人工开辟新的 workspace")
    return f"run_v{nxt:03d}"


def render(text: str, values: dict[str, str], name: str) -> str:
    tokens = geomlib.template_tokens(text)
    missing = sorted(t for t in tokens if t not in values)
    if missing:
        fail(f"{name} 存在未知/未提供值的占位符: {', '.join(missing)}")
    for key, val in values.items():
        text = text.replace(key, str(val))
    left = geomlib.template_tokens(text)
    if left:
        fail(f"{name} 渲染后仍有未替换占位符: {', '.join(sorted(left))}")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--scan-id", required=True)
    ap.add_argument("--geom", required=True)
    ap.add_argument("--structure", required=True)
    ap.add_argument("--potentials", required=True)
    ap.add_argument("--template", default=None)
    ap.add_argument("--scan-csv", default=None)
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    params = geomlib.load_json(config_path)
    root = geomlib.resolve_project_root(config_path, params)
    workspace = root / params["paths"]["workspace"] if "paths" in params else root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    template_path = Path(args.template) if args.template else root / "templates" / "in.pattern.template"
    scan_csv = Path(args.scan_csv) if args.scan_csv else root / "config" / "scan.csv"
    geom_path = Path(args.geom).resolve()
    structure_path = Path(args.structure).resolve()
    potentials_path = Path(args.potentials).resolve()

    for p, label in (
        (template_path, "模板"),
        (geom_path, "geom.json"),
        (structure_path, "structure.data"),
        (potentials_path, "potentials.in"),
    ):
        if not p.exists():
            fail(f"缺少{label}: {p}")

    template_text = template_path.read_text(encoding="utf-8")
    tokens = geomlib.template_tokens(template_text)
    missing = REQUIRED_TOKENS - tokens
    if missing:
        fail(f"模板缺少必需占位符: {', '.join(sorted(missing))}")

    geom = geomlib.load_json(geom_path)
    report = geomlib.validate_geom(geom, params.get("thresholds", {}), allow_draft=False,
                                   bin_a=float(params["run"]["chunk_bin_A"]))
    if report["errors"]:
        for e in report["errors"]:
            print(f"  - {e}", file=sys.stderr)
        fail("geom.json 未通过校验，拒绝建版")

    row = read_scan_row(scan_csv, args.scan_id)
    if row.get("status", "pending") not in ("pending", ""):
        fail(f"scan_id={args.scan_id} 状态为 {row.get('status')}，不重复建版")

    run_id = next_run_id(workspace)
    final_dir = workspace / run_id
    tmp_dir = workspace / f".{run_id}.tmp.{os.getpid()}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    run_cfg = params["run"]
    values = {
        "__STRUCTURE__": "../structure.data",
        "__HOT_ZLO__": f"{float(geom['groups']['hot']['z_min']):.6f}",
        "__HOT_ZHI__": f"{float(geom['groups']['hot']['z_max']):.6f}",
        "__COLD_ZLO__": f"{float(geom['groups']['cold']['z_min']):.6f}",
        "__COLD_ZHI__": f"{float(geom['groups']['cold']['z_max']):.6f}",
        "__T_EQ__": "300.0",
        "__DT__": f"{float(run_cfg['timestep_ps']):.6g}",
        "__N_EQUIL__": str(int(run_cfg["n_equil_steps"])),
        "__N_PROD__": str(int(run_cfg["n_prod_steps"])),
        "__THERMO__": str(int(run_cfg["thermo_every"])),
        "__BIN__": f"{float(run_cfg['chunk_bin_A']):.6g}",
        "__AVE_NEVERY__": str(int(run_cfg["ave_nevery"])),
        "__AVE_NREPEAT__": str(int(run_cfg["ave_nrepeat"])),
        "__AVE_NFREQ__": str(int(run_cfg["ave_nfreq"])),
        "__FLUX__": f"{float(params['flux_ev_per_ps']):.10g}",
    }

    try:
        tmp_dir.mkdir(parents=False, exist_ok=False)
        shutil.copy2(structure_path, tmp_dir / "structure.data")
        shutil.copy2(potentials_path, tmp_dir / "potentials.in")
        shutil.copy2(geom_path, tmp_dir / "geom.json")
        shutil.copy2(config_path, tmp_dir / "params.snapshot.json")
        shutil.copy2(template_path, tmp_dir / "in.pattern.template")

        seed_dirs = []
        for seed in params["seeds"]:
            seed_dir = tmp_dir / f"seed_{int(seed)}"
            seed_dir.mkdir()
            vals = dict(values)
            vals["__SEED__"] = str(int(seed))
            rendered = render(template_text, vals, f"seed_{seed}/in.pattern")
            (seed_dir / "in.pattern").write_text(rendered, encoding="utf-8", newline="\n")
            seed_dirs.append(seed_dir.name)

        meta = {
            "schema_version": "1.0",
            "run_id": run_id,
            "scan": row,
            "geometry": {
                "geometry_id": geom.get("geometry_id"),
                "status": geom.get("status"),
                "sha256": geomlib.sha256_file(geom_path),
            },
            "inputs": {
                "structure": {"path": str(structure_path), "sha256": geomlib.sha256_file(structure_path)},
                "potentials": {"path": str(potentials_path), "sha256": geomlib.sha256_file(potentials_path)},
                "template": {"path": str(template_path), "sha256": geomlib.sha256_file(template_path)},
                "params": {"path": str(config_path), "sha256": geomlib.sha256_file(config_path)},
            },
            "seeds": [int(s) for s in params["seeds"]],
            "seed_dirs": seed_dirs,
            "launch_mode": params["lammps"]["launch_mode"],
            "state": "CREATED",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "host": socket.gethostname(),
            "platform": platform.platform(),
        }
        geomlib.dump_json(tmp_dir / "run_meta.json", meta)

        lines = []
        lines.append("=" * 78)
        lines.append(f"{run_id}  {row.get('scan_id', '')}")
        lines.append(f"几何参数: W={row.get('W_nm')} nm  D={row.get('D_nm')} nm  "
                     f"P={row.get('P_nm')} nm  t={row.get('t_nm')} nm  "
                     f"phi={row.get('phi_deg')} deg  side={row.get('sided')}")
        lines.append(f"geom_id : {geom.get('geometry_id')}")
        lines.append(f"热流    : {params['flux_ev_per_ps']} eV/ps  (params.json)")
        lines.append(f"生产步数: {run_cfg['n_prod_steps']}  dt={run_cfg['timestep_ps']} ps")
        lines.append(f"种子    : {params['seeds']}")
        lines.append(f"LAMMPS  : {params['lammps']['exe']}  mode={params['lammps']['launch_mode']}")
        lines.append("-" * 78)
        lines.append("输入哈希见 manifest.sha256；任何输入变更都必须新建 run_vNNN。")
        lines.append("执行顺序: preflight -> run_seed (每个 seed) -> postprocess -> qc_check")
        lines.append("=" * 78)
        (tmp_dir / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

        manifest = []
        skip = {"manifest.sha256", "README.txt", "run_meta.json"}
        for path in sorted(tmp_dir.rglob("*")):
            if path.is_file() and path.name not in skip:
                rel = path.relative_to(tmp_dir).as_posix()
                manifest.append(f"{geomlib.sha256_file(path)}  {rel}")
        (tmp_dir / "manifest.sha256").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        (tmp_dir / ".lock").write_text(
            json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                        "created_at": meta["created_at"]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

        os.rename(tmp_dir, final_dir)
    except BaseException:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    print(f"RUN_DIR={final_dir}")
    print(f"RUN_ID={run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
