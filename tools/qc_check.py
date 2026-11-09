#!/usr/bin/env python3
"""Apply every quality gate and emit the archived result row.

Inputs : <run>/seed_*/result.json, run_meta.json, geom.json, params.snapshot.json
Outputs: <run>/qc.json, <run>/tbr_result.csv, <run>/report.txt
         <workspace>/ledger.csv (append-only)

Exit codes: 0 pass, 3 QC fail, 2 input error.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402

CSV_HEADER = [
    "version", "params_W", "params_D", "params_t", "TBR_mean", "TBR_std",
    "seed_valid_count", "is_passed", "note",
    "params_P", "params_phi", "sided", "TBR_relstd", "n_seeds",
    "TBR_iface_mean", "geom_sha256", "params_sha256", "finished_at",
]


def fnum(x, nd=6):
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}g}"
    return str(x)


def seed_checks(res: dict, params: dict, th: dict) -> dict:
    checks: dict[str, bool | str | None] = {}
    q = params.get("quality", {})
    checks["parse_ok"] = res.get("status") == "OK"
    checks["exit_zero"] = res.get("exit_code") == 0
    checks["log_complete"] = bool(res.get("checks", {}).get("log_complete"))
    checks["no_lost_atoms"] = not bool(res.get("checks", {}).get("lost_atoms"))
    crit = (res.get("checks", {}).get("minimize_criterion") or "").lower()
    checks["minimize_converged"] = crit in ("energy tolerance", "force tolerance")
    if q.get("require_minimize_energy_tolerance"):
        checks["minimize_converged"] = crit == "energy tolerance"

    counts = res.get("counts") or {}
    if q.get("require_equal_hot_cold_counts", True):
        checks["net_flux_zero"] = (
            counts.get("hot") is not None
            and counts.get("cold") is not None
            and counts["hot"] == counts["cold"]
            and counts["hot"] > 0
        )
    else:
        checks["net_flux_zero"] = True

    energy = res.get("energy") or {}
    checks["flux_symmetry"] = float(energy.get("flux_symmetry_rel", math.inf)) <= float(
        th["flux_symmetry_max_rel"]
    )
    checks["toteng_drift"] = float(energy.get("toteng_drift_rel", math.inf)) <= float(
        th["toteng_drift_max_rel"]
    )
    checks["dT_signal"] = float(res.get("dT_total_K", -1)) > float(th["dT_total_min_K"])

    fit_ok = True
    for itf in res.get("interfaces") or []:
        for side in ("left", "right"):
            s = itf.get(side) or {}
            if int(s.get("n_points", 0)) < int(th["fit_min_points"]):
                fit_ok = False
            if float(s.get("r2", 0.0)) < float(th["fit_r2_min"]):
                fit_ok = False
    checks["fit_quality"] = fit_ok

    tbr = res.get("tbr_total_m2KW")
    checks["tbr_in_range"] = (
        tbr is not None
        and float(th["tbr_min_m2KW"]) <= float(tbr) <= float(th["tbr_max_m2KW"])
    )

    tc = res.get("time_convergence")
    checks["time_converged"] = (
        tc is not None and float(tc.get("rel_diff", math.inf)) <= float(th["time_convergence_max_rel"])
    )

    temp = res.get("temperature") or {}
    checks["temp_stable"] = abs(float(temp.get("drift_K", math.inf))) <= float(
        th["temp_stability_max_K"]
    )
    return checks


def verify_manifest(run_dir: Path) -> tuple[bool, str]:
    p = run_dir / "manifest.sha256"
    if not p.exists():
        return False, "manifest.sha256 缺失"
    bad = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            return False, f"manifest 行格式错误: {line[:60]}"
        digest, rel = parts
        f = run_dir / rel
        if not f.exists():
            bad.append(f"{rel}(缺失)")
        elif geomlib.sha256_file(f) != digest:
            bad.append(f"{rel}(哈希不符)")
    if bad:
        return False, "; ".join(bad[:5])
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--rewrite", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    params = geomlib.load_json(run_dir / "params.snapshot.json")
    meta = geomlib.load_json(run_dir / "run_meta.json")
    geom = geomlib.load_json(run_dir / "geom.json")
    th = params["thresholds"]

    results, per_seed = [], {}
    for seed in params["seeds"]:
        rp = run_dir / f"seed_{seed}" / "result.json"
        if not rp.exists():
            per_seed[f"seed_{seed}"] = {"valid": False, "reason": "result.json 缺失（未后处理）"}
            continue
        res = geomlib.load_json(rp)
        checks = seed_checks(res, params, th)
        # provenance: log must be unchanged since post-processing
        log_path = run_dir / f"seed_{seed}" / "log.pattern"
        hash_ok = log_path.exists() and geomlib.sha256_file(log_path) == res.get("log_sha256")
        checks["log_unmodified"] = hash_ok
        valid = all(bool(v) for v in checks.values())
        results.append(res if valid else None)
        per_seed[f"seed_{seed}"] = {
            "valid": valid,
            "tbr_total_m2KW": res.get("tbr_total_m2KW"),
            "dT_total_K": res.get("dT_total_K"),
            "checks": checks,
        }

    valid = [r for r in results if r]
    n_valid = len(valid)
    tbrs = [float(r["tbr_total_m2KW"]) for r in valid]
    if n_valid >= 2:
        mean = statistics.fmean(tbrs)
        std = statistics.stdev(tbrs)
        relstd = std / mean if mean else math.inf
    elif n_valid == 1:
        mean, std, relstd = tbrs[0], 0.0, 0.0
    else:
        mean = std = relstd = None

    group_checks = {
        "manifest_ok": False,
        "all_seeds_valid": n_valid == len(params["seeds"]),
        "n_valid_ge_3": n_valid >= 3,
        "relstd_ok": relstd is not None and relstd <= float(th["tbr_relstd_max"]),
        "geom_approved": geom.get("status") == "APPROVED",
    }
    manifest_ok, manifest_detail = verify_manifest(run_dir)
    group_checks["manifest_ok"] = manifest_ok
    passed = bool(
        all(group_checks.values())
        and n_valid == len(params["seeds"])
    )

    notes = []
    for k, v in group_checks.items():
        if not v:
            notes.append(f"{k}=False" + (f"({manifest_detail})" if k == "manifest_ok" else ""))
    if not passed:
        for seed, info in per_seed.items():
            if not info.get("valid"):
                bad = [k for k, v in (info.get("checks") or {}).items() if not v]
                notes.append(f"{seed}:" + ("/".join(bad) if bad else info.get("reason", "invalid")))
    note = "; ".join(notes) if notes else "ok"

    qc = {
        "schema_version": "1.0",
        "run_id": meta.get("run_id", run_dir.name),
        "scan": meta.get("scan", {}),
        "per_seed": per_seed,
        "group_checks": group_checks,
        "n_valid": n_valid,
        "n_seeds": len(params["seeds"]),
        "TBR_mean_m2KW": mean,
        "TBR_std_m2KW": std,
        "TBR_relstd": relstd,
        "is_passed": passed,
        "note": note,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    geomlib.dump_json(run_dir / "qc.json", qc)

    csv_path = run_dir / "tbr_result.csv"
    if csv_path.exists() and not args.rewrite:
        print(f"[QC][FAIL] {csv_path} 已存在；结果不可覆盖。确需重算请人工加 --rewrite。", file=sys.stderr)
        return 3

    scan = meta.get("scan", {})
    row = {
        "version": run_dir.name,
        "params_W": scan.get("W_nm", ""),
        "params_D": scan.get("D_nm", ""),
        "params_t": scan.get("t_nm", ""),
        "TBR_mean": fnum(mean, 8),
        "TBR_std": fnum(std, 8),
        "seed_valid_count": n_valid,
        "is_passed": "True" if passed else "False",
        "note": note.replace("\n", " ")[:400],
        "params_P": scan.get("P_nm", ""),
        "params_phi": scan.get("phi_deg", ""),
        "sided": scan.get("sided", ""),
        "TBR_relstd": fnum(relstd, 6),
        "n_seeds": len(params["seeds"]),
        "TBR_iface_mean": fnum(
            statistics.fmean([float(r["tbr_iface_mean_m2KW"]) for r in valid])
            if valid else None, 8
        ),
        "geom_sha256": meta.get("geometry", {}).get("sha256", ""),
        "params_sha256": meta.get("inputs", {}).get("params", {}).get("sha256", ""),
        "finished_at": qc["checked_at"],
    }
    tmp = csv_path.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        w.writeheader()
        w.writerow(row)
    os.replace(tmp, csv_path)

    # interface detail
    with open(run_dir / "interfaces.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["version", "seed", "interface", "z_A", "dT_K", "TBR_m2KW",
                     "r2_left", "r2_right", "n_left", "n_right"])
        for r in valid:
            for itf in r.get("interfaces", []):
                w.writerow([
                    run_dir.name, r["seed"], itf.get("id"), fnum(itf.get("z")),
                    fnum(itf.get("dT_K")), fnum(float(itf["dT_K"]) / float(r["q_W_m2"])),
                    fnum(itf["left"].get("r2")), fnum(itf["right"].get("r2")),
                    itf["left"].get("n_points"), itf["right"].get("n_points"),
                ])

    lines = [
        "=" * 52,
        "",
        f"{run_dir.name} 仿真完成",
        f"几何参数 W={scan.get('W_nm','')} , D={scan.get('D_nm','')} , "
        f"P={scan.get('P_nm','')} , t={scan.get('t_nm','')} , phi={scan.get('phi_deg','')}",
        f"有效种子数目：{n_valid} /{len(params['seeds'])}",
        f"TBR = {fnum(mean,4)} ± {fnum(std,4)} [m2*K/W]"
        if mean is not None else "TBR = 无有效数据",
        f"相对标准差：{fnum(relstd*100 if relstd is not None else None, 3)} %",
        f"标准差是否小于 10%：{'是' if relstd is not None and relstd <= float(th['tbr_relstd_max']) else '否'}",
        f"本组是否通过全部质控：{'是' if passed else '否'}",
        f"备注：{note}",
        "",
        "=" * 52,
        "",
        "请人类指示下一步：修改参数 / 继续扫描 / 终止任务",
        "",
    ]
    (run_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8-sig")

    ledger = run_dir.parent / "ledger.csv"
    new_file = not ledger.exists()
    with open(ledger, "a", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["timestamp", "run_id", "scan_id", "state", "TBR_mean",
                        "TBR_relstd", "n_valid", "is_passed", "note"])
        w.writerow([qc["checked_at"], run_dir.name, scan.get("scan_id", ""),
                    "PASSED" if passed else "QC_FAILED",
                    fnum(mean, 8), fnum(relstd, 6), n_valid,
                    "True" if passed else "False", note.replace("\n", " ")[:300]])

    print(f"[QC] {run_dir.name}: {'PASS' if passed else 'FAIL'}  n_valid={n_valid}  "
          f"TBR={fnum(mean,4)} +/- {fnum(std,4)}  relstd={fnum(relstd,3)}")
    print(f"[QC] 报告: {run_dir / 'report.txt'}")
    return 0 if passed else 3


if __name__ == "__main__":
    sys.exit(main())
