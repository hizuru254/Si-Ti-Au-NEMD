#!/usr/bin/env python3
"""Gate 0: environment + input contract verification.

Exit codes: 0 ready, 2 blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402
import new_run  # noqa: E402


def _read_lock(path: Path):
    return geomlib.load_json(path) if path.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--geom", required=True)
    ap.add_argument("--structure", required=True)
    ap.add_argument("--potentials", required=True)
    ap.add_argument("--template", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-draft", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    params = geomlib.load_json(config_path)
    root = geomlib.resolve_project_root(config_path, params)
    checks = []

    def add(name: str, ok: bool, detail: str, severity: str = "error") -> None:
        checks.append({"check": name, "ok": bool(ok), "severity": severity, "detail": detail})

    # 1. path / encoding -----------------------------------------------------
    ascii_ok = geomlib.is_ascii_path(root)
    launch = params["lammps"]["launch_mode"]
    if ascii_ok:
        add("path_ascii", True, str(root))
    else:
        add("path_ascii", False,
            f"项目根含非 ASCII 字符: {root}；LAMMPS 会报 'Detected non-ASCII characters'（实测）",
            severity="error" if launch == "mpi" else "warning")

    # 2. LAMMPS --------------------------------------------------------------
    exe = Path(params["lammps"]["exe"])
    if not exe.exists():
        add("lammps_exe", False, f"不存在: {exe}")
    else:
        try:
            proc = subprocess.run([str(exe), "-log", "none"], input="quit\n",
                                  capture_output=True, text=True,
                                  timeout=60, errors="replace")
            out = ((proc.stdout or "") + (proc.stderr or "")).lstrip()
            banner = out.splitlines()[0] if out.strip() else ""
            marker = params["lammps"].get("version_marker", "")
            add("lammps_exe", True, f"{exe} | {banner}")
            add("lammps_version", marker in out,
                f"期望包含 {marker!r}，实际首行 {banner!r}")
        except Exception as exc:  # noqa: BLE001
            add("lammps_exe", False, f"无法执行 {exe}: {exc}")

    # 3. python / numpy ------------------------------------------------------
    add("python_version", sys.version_info >= (3, 10),
        f"{sys.version.split()[0]} (要求 >=3.10)")
    try:
        import numpy  # noqa: F401
        add("numpy", True, f"numpy {numpy.__version__}")
    except Exception as exc:  # noqa: BLE001
        add("numpy", False, f"postprocess 需要 numpy: {exc}")

    # 4. disk ---------------------------------------------------------------
    try:
        gb = geomlib.free_gb(root if root.exists() else Path.cwd())
        add("disk_space", gb >= float(params["disk_min_free_gb"]),
            f"{gb:.1f} GB 可用，阈值 {params['disk_min_free_gb']} GB")
    except Exception as exc:  # noqa: BLE001
        add("disk_space", True, f"无法读取磁盘信息（不阻塞）: {exc}", severity="warning")

    # 4. inputs -------------------------------------------------------------
    template = Path(args.template) if args.template else root / "templates" / "in.pattern.template"
    structure = Path(args.structure).resolve()
    potentials = Path(args.potentials).resolve()
    geom_path = Path(args.geom).resolve()
    for p, label in ((template, "模板"), (structure, "structure.data"),
                     (potentials, "potentials.in"), (geom_path, "geom.json")):
        add(f"file_{label}", p.exists(), str(p))

    if template.exists():
        text = template.read_text(encoding="utf-8")
        tokens = geomlib.template_tokens(text)
        missing = new_run.REQUIRED_TOKENS - tokens
        add("template_tokens", not missing,
            "缺失: " + ", ".join(sorted(missing)) if missing else "完整")

    # 5. geometry -----------------------------------------------------------
    geom = None
    if geom_path.exists():
        geom = geomlib.load_json(geom_path)
        rep = geomlib.validate_geom(geom, params["thresholds"], allow_draft=args.allow_draft,
                                    bin_a=float(params["run"]["chunk_bin_A"]))
        add("geom_schema", not rep["errors"],
            "; ".join(rep["errors"]) if rep["errors"] else
            f"{rep['n_layers']} layers / {rep['n_interfaces']} interfaces, status={rep['status']}")
        for w in rep["warnings"]:
            add("geom_warning", True, w, severity="warning")

    # 6. structure ----------------------------------------------------------
    if structure.exists() and geom:
        try:
            hdr = geomlib.read_data_header(structure)
            box = hdr["box"]
            ok = hdr["n_atoms"] and hdr["n_atoms"] > 0 and hdr["n_types"]
            add("data_header", bool(ok),
                f"atoms={hdr['n_atoms']} types={hdr['n_types']} box={box} triclinic={hdr['triclinic']}")
            if ok:
                g = geom["groups"]
                counts = geomlib.count_atoms_by_z(structure, {
                    "hot": (float(g["hot"]["z_min"]), float(g["hot"]["z_max"])),
                    "cold": (float(g["cold"]["z_min"]), float(g["cold"]["z_max"])),
                })
                add("group_counts", counts["hot"] == counts["cold"] and counts["hot"] > 0,
                    f"hot={counts['hot']} cold={counts['cold']}（必须相等且>0，否则净热流不为零）")
                bin_a = float(geom.get("chunk_bin_A", params["run"]["chunk_bin_A"]))
                for itf in geom.get("interfaces") or []:
                    for side in ("left", "right"):
                        w = itf[side]
                        c = geomlib.count_atoms_by_z(structure, {"w": (float(w["z_min"]), float(w["z_max"]))})["w"]
                        nbin = max(1, int(round((float(w["z_max"]) - float(w["z_min"])) / bin_a)))
                        add(f"window_atoms_{itf.get('id')}_{side}", c >= 10 * nbin,
                            f"{c} atoms / {nbin} bins = {c / nbin:.0f} 每 bin（建议 ≥10）")
            if ok and not hdr["triclinic"] and len(box) == 6:
                lx = box["xhi"] - box["xlo"]
                ly = box["yhi"] - box["ylo"]
                gx, gy = float(geom["box"]["lx"]), float(geom["box"]["ly"])
                add("data_vs_geom_xy", abs(lx - gx) / gx <= 0.005 and abs(ly - gy) / gy <= 0.005,
                    f"data {lx:.4f}x{ly:.4f} Å vs geom {gx:.4f}x{gy:.4f} Å (容差 0.5%)")
                add("data_vs_geom_z",
                    abs(box["zlo"] - float(geom["box"]["z_min"])) <= 0.5
                    and abs(box["zhi"] - float(geom["box"]["z_max"])) <= 0.5,
                    f"data z {box['zlo']:.3f}..{box['zhi']:.3f} vs geom "
                    f"{geom['box']['z_min']}..{geom['box']['z_max']}")
            elif hdr["triclinic"]:
                add("data_triclinic", False, "暂不支持三斜盒子：热流面积需另算")
            exp = (geom.get("expected_atoms") or {}).get("total")
            if exp:
                add("data_atom_count", hdr["n_atoms"] == exp,
                    f"data {hdr['n_atoms']} vs geom.expected_atoms {exp}")
            if potentials.exists():
                ptext = potentials.read_text(encoding="utf-8", errors="replace")
                ntypes = hdr["n_types"] or 0
                ncoeff = len(re.findall(r"^\s*pair_coeff\b", ptext, flags=re.M))
                add("potential_coeff_count", ncoeff > 0,
                    f"pair_coeff 行数={ncoeff}, atom types={ntypes}（人工核对每个 type 已覆盖）")
                add("potential_has_pair_style", "pair_style" in ptext,
                    "potentials.in 必须包含 pair_style")
        except Exception as exc:  # noqa: BLE001
            add("data_header", False, f"读取失败: {exc}")

    # 7. potentials lock ----------------------------------------------------
    base_lock = _read_lock(root / "config" / "potentials.lock.json")
    run_lock = _read_lock(config_path.parent / "potentials.lock.json")
    lock = run_lock if run_lock is not None else base_lock
    if lock is not None:
        entries = lock.get("files", {})
        pot_dir = Path(params["potentials_dir"]) if params.get("potentials_dir") else None
        for name, entry in entries.items():
            expected = (entry or {}).get("sha256")
            if not expected:
                continue
            target = Path(name)
            if not target.is_absolute():
                candidates = [potentials.parent / name, root / name]
                if pot_dir is not None:
                    candidates.insert(1, pot_dir / name)
                target = next((c for c in candidates if c.exists()), target)
            if not target.exists():
                add(f"potential_file_{name}", False, f"找不到 {name}")
                continue
            actual = geomlib.sha256_file(target)
            add(f"potential_hash_{name}", actual == expected,
                f"{name}: {actual[:16]}… vs lock {str(expected)[:16]}…")
        add("potential_approved", lock.get("status") == "APPROVED",
            f"lock.status={lock.get('status')}")
        bv = lock.get("bulk_validation") or {}
        verdict = bv.get("verdict")
        allow_waiver = bool(params.get("quality", {}).get("allow_bulk_waiver"))
        add("bulk_validation", verdict == "PASS" or (verdict == "WAIVED" and allow_waiver),
            f"bulk_validation.verdict={verdict}"
            + ("（已按 params 允许 WAIVED）" if verdict == "WAIVED" and allow_waiver else "（要求 PASS）"))
    else:
        add("potential_lock", False, "缺少 potentials.lock.json（生产运行必须补齐）")

    # 8. dry run ------------------------------------------------------------
    if args.dry_run and geom and template.exists() and structure.exists() and potentials.exists():
        tmp = root / ".preflight" / f"tmp_{os.getpid()}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copy2(structure, tmp / "structure.data")
            shutil.copy2(potentials, tmp / "potentials.in")
            seed_dir = tmp / "seed_1001"
            seed_dir.mkdir()
            run_cfg = params["run"]
            values = {
                "__STRUCTURE__": "../structure.data",
                "__HOT_ZLO__": f"{float(geom['groups']['hot']['z_min']):.6f}",
                "__HOT_ZHI__": f"{float(geom['groups']['hot']['z_max']):.6f}",
                "__COLD_ZLO__": f"{float(geom['groups']['cold']['z_min']):.6f}",
                "__COLD_ZHI__": f"{float(geom['groups']['cold']['z_max']):.6f}",
                "__SEED__": "1001",
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
                "__N_WARM__": str(int(run_cfg["n_warm_steps"])),
                "__T_ANN__": f"{float(run_cfg['t_anneal']):.1f}",
                "__N_ANN_UP__": str(int(run_cfg["n_ann_up"])),
                "__N_ANN_HOLD__": str(int(run_cfg["n_ann_hold"])),
                "__N_ANN_DOWN__": str(int(run_cfg["n_ann_down"])),
            }
            rendered = new_run.render(template.read_text(encoding="utf-8"), values, "dryrun")
            (seed_dir / "in.pattern").write_text(rendered, encoding="utf-8", newline="\n")
            cmd = [str(exe), "-skiprun", "-in", "in.pattern", "-log", "log.dryrun"]
            proc = subprocess.run(cmd, cwd=str(seed_dir), capture_output=True, text=True,
                                  timeout=int(params["timeouts_s"]["dryrun"]), errors="replace")
            log = (seed_dir / "log.dryrun")
            log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            err_lines = [ln for ln in log_text.splitlines() if ln.startswith("ERROR")]
            add("dry_run", proc.returncode == 0 and not err_lines,
                f"exit={proc.returncode} " + ("; ".join(err_lines[:3]) if err_lines else "无 ERROR"))
        except Exception as exc:  # noqa: BLE001
            add("dry_run", False, f"干跑失败: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]

    print("=" * 78)
    print(f"PREFLIGHT  {root}")
    print("=" * 78)
    for c in checks:
        flag = "PASS" if c["ok"] else ("WARN" if c["severity"] == "warning" else "FAIL")
        print(f"  [{flag:4}] {c['check']:<24} {c['detail']}")
    print("-" * 78)
    print(f"结果: {'READY' if not errors else 'BLOCKED'}   errors={len(errors)} warnings={len(warnings)}")

    report = {
        "schema_version": "1.0",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_root": str(root),
        "config": str(config_path),
        "geom": str(geom_path),
        "structure": str(structure),
        "potentials": str(potentials),
        "checks": checks,
        "errors": [c["check"] for c in errors],
        "warnings": [c["check"] for c in warnings],
        "verdict": "READY" if not errors else "BLOCKED",
    }
    out = root / "logs" / "preflight_report.json"
    geomlib.dump_json(out, report)
    print(f"报告: {out}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
