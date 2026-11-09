#!/usr/bin/env python3
"""Canonical NEMD post-processing.  No smoothing, no interpolation, no guesses.

Reads:  <run>/seed_XXXX/log.pattern, profile.txt, run_meta.json, geom.json,
        params.snapshot.json
Writes: <run>/seed_XXXX/result.json

Exit codes: 0 ok, 2 input/parse error.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402

NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
GEOM_RE = re.compile(
    rf"GEOM\s+lx=({NUM})\s+ly=({NUM})(?:\s+lz=({NUM}))?"
)
COUNTS_RE = re.compile(r"COUNTS\s+hot=(\d+)\s+cold=(\d+)")
CRIT_RE = re.compile(r"Stopping criterion\s*=\s*(.+)")


class ParseError(RuntimeError):
    pass


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_thermo(text: str) -> list[tuple[list[str], list[list[float]]]]:
    lines = text.splitlines()
    tables: list[tuple[list[str], list[list[float]]]] = []
    i = 0
    while i < len(lines):
        if re.match(r"^\s*Step\s+", lines[i]) and "TotEng" in lines[i]:
            header = lines[i].split()
            rows: list[list[float]] = []
            j = i + 1
            while j < len(lines):
                s = lines[j].strip()
                if not s:
                    break
                parts = s.split()
                if not re.match(r"^[+-]?\d+$", parts[0]):
                    break
                try:
                    vals = [float(x) for x in parts]
                except ValueError:
                    break
                if len(vals) != len(header):
                    break
                rows.append(vals)
                j += 1
            tables.append((header, rows))
            i = j
        else:
            i += 1
    return tables


def parse_profile(path: Path) -> list[dict]:
    blocks: list[dict] = []
    for raw in read_text(path).splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("%"):
            continue
        parts = s.split()
        if len(parts) == 3:
            blocks.append({"step": int(parts[0]), "nchunks": int(parts[1]), "rows": []})
        elif len(parts) == 4:
            if not blocks:
                raise ParseError("profile.txt 第一行数据不是 'Timestep Nchunks Total'")
            blocks[-1]["rows"].append([float(x) for x in parts])
        elif len(parts) == 5:
            raise ParseError(
                "profile.txt 为 5 列（可能同时输出了 density/mass）。"
                "fix ave/chunk 只允许输出 temp，保持 4 列。"
            )
        else:
            raise ParseError(f"profile.txt 无法识别的行: {s[:80]}")
    for b in blocks:
        if len(b["rows"]) != b["nchunks"]:
            raise ParseError(
                f"profile 块 step={b['step']} 声明 {b['nchunks']} 个 chunk，"
                f"实际 {len(b['rows'])} 行"
            )
    return blocks


def average_blocks(blocks: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Average T per chunk over blocks; empty chunks (vacuum) stay NaN."""
    if not blocks:
        raise ParseError("没有可用的 profile 块")
    n = blocks[0]["nchunks"]
    acc_t = np.zeros(n, dtype=float)
    acc_z = np.zeros(n, dtype=float)
    cnt = np.zeros(n, dtype=int)
    for b in blocks:
        if b["nchunks"] != n:
            raise ParseError("不同 profile 块的 chunk 数不一致")
        arr = np.array(b["rows"], dtype=float)
        occupied = arr[:, 2] > 0
        acc_t[occupied] += arr[occupied, 3]
        acc_z += arr[:, 1]
        cnt[occupied] += 1
    z = acc_z / len(blocks)
    t = np.where(cnt > 0, acc_t / np.maximum(cnt, 1), np.nan)
    return z, t, cnt


def linear_fit(z: np.ndarray, t: np.ndarray) -> dict:
    n = len(z)
    if n < 2:
        raise ParseError("拟合点数不足")
    coef = np.polyfit(z, t, 1)
    pred = np.polyval(coef, z)
    ss_res = float(np.sum((t - pred) ** 2))
    ss_tot = float(np.sum((t - np.mean(t)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return {"slope": float(coef[0]), "intercept": float(coef[1]), "r2": r2, "n_points": n}


def fit_interface(z: np.ndarray, t: np.ndarray, itf: dict, th: dict) -> dict:
    out = {"id": itf.get("id"), "z": float(itf["z"])}
    for side in ("left", "right"):
        win = itf[side]
        wlo, whi = float(win["z_min"]), float(win["z_max"])
        mask = (z >= wlo) & (z <= whi)
        if mask.sum() == 0:
            raise ParseError(f"界面 {out['id']} {side} 窗口内没有 chunk")
        if not np.isfinite(t[mask]).all():
            raise ParseError(f"界面 {out['id']} {side} 窗口内有空 chunk（真空或原子丢失）")
        zz, tt = z[mask], t[mask]
        fit = linear_fit(zz, tt)
        out[side] = {
            "z_min": wlo,
            "z_max": whi,
            "n_points": fit["n_points"],
            "r2": fit["r2"],
            "slope_K_per_A": fit["slope"],
            "T_at_interface_K": float(np.polyval([fit["slope"], fit["intercept"]], out["z"])),
        }
        if fit["n_points"] < int(th.get("fit_min_points", 4)):
            raise ParseError(f"界面 {out['id']} {side} 仅 {fit['n_points']} 个点")
        if fit["r2"] < float(th.get("fit_r2_min", 0.995)):
            out[side]["r2_below_threshold"] = True
    out["dT_K"] = abs(out["left"]["T_at_interface_K"] - out["right"]["T_at_interface_K"])
    return out


def compute_tbr(z: np.ndarray, t: np.ndarray, geom: dict, q_w_m2: float, th: dict) -> dict:
    ifaces = [fit_interface(z, t, itf, th) for itf in geom["interfaces"]]
    dts = [it["dT_K"] for it in ifaces]
    total = float(sum(dts))
    return {
        "interfaces": ifaces,
        "dT_total_K": total,
        "tbr_total_m2KW": total / q_w_m2,
        "tbr_iface_mean_m2KW": (total / len(dts)) / q_w_m2 if dts else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--config", default=None, help="未使用；为兼容而保留")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    seed_dir = run_dir / args.seed
    params = geomlib.load_json(run_dir / "params.snapshot.json")
    geom = geomlib.load_json(run_dir / "geom.json")
    th = params.get("thresholds", {})
    run_cfg = params["run"]

    log_path = seed_dir / "log.pattern"
    prof_path = seed_dir / "profile.txt"
    for p in (log_path, prof_path):
        if not p.exists():
            print(f"[POST][FAIL] 缺少 {p}", file=sys.stderr)
            return 2

    text = read_text(log_path)
    meta_path = seed_dir / "run_meta.json"
    seed_meta = geomlib.load_json(meta_path) if meta_path.exists() else {}

    result: dict = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "seed": args.seed,
        "log_sha256": geomlib.sha256_file(log_path),
        "profile_sha256": geomlib.sha256_file(prof_path),
        "exit_code": seed_meta.get("exit_code"),
        "wall_time_s": seed_meta.get("wall_time_s"),
    }

    prev_path = seed_dir / "result.json"
    if prev_path.exists():
        prev = geomlib.load_json(prev_path)
        if prev.get("log_sha256") and prev["log_sha256"] != result["log_sha256"]:
            print(f"[POST][FAIL] {args.seed}: log.pattern 与已有 result.json 的哈希不一致，"
                  "日志在取证后被修改。禁止重算覆盖，必须新建 run。", file=sys.stderr)
            return 2

    try:
        m = GEOM_RE.search(text)
        if not m:
            raise ParseError("日志中缺少 'GEOM lx=... ly=...' 行；模板必须打印该行")
        lx, ly = float(m.group(1)), float(m.group(2))
        if lx <= 0 or ly <= 0:
            raise ParseError("GEOM 的 lx/ly 非正")
        area = lx * ly

        c = COUNTS_RE.search(text)
        nhot = int(c.group(1)) if c else None
        ncold = int(c.group(2)) if c else None

        tables = parse_thermo(text)
        prod = [(h, r) for (h, r) in tables if "f_hot" in h and "f_cold" in h]
        if not prod:
            raise ParseError("日志中找不到含 f_hot/f_cold 的生产段热力学表；模板必须输出 fix 标量")
        header, rows = prod[-1]
        if not rows:
            raise ParseError("生产段热力学表为空")
        idx = {name: header.index(name) for name in header}
        steps = np.array([r[idx["Step"]] for r in rows], dtype=float)
        nprod = int(run_cfg["n_prod_steps"])
        if int(steps[0]) != 0:
            raise ParseError(f"生产段首个热力学步为 {int(steps[0])}，应为 0（reset_timestep 后）")
        if int(steps[-1]) != nprod:
            raise ParseError(f"生产段末步为 {int(steps[-1])}，应为 {nprod}；日志可能截断")

        toteng = np.array([r[idx["TotEng"]] for r in rows], dtype=float)
        temp = np.array([r[idx["Temp"]] for r in rows], dtype=float)
        f_hot = np.array([r[idx["f_hot"]] for r in rows], dtype=float)
        f_cold = np.array([r[idx["f_cold"]] for r in rows], dtype=float)

        # fix heat scalar is the instantaneous flux, not a cumulative integral.
        # Net injected power is zero by construction (equal counts, +/- same eflux);
        # conservation is therefore measured on TotEng drift, and the two fix
        # scalars are only cross-checked for symmetry.
        fh_mean = float(np.mean(f_hot))
        fc_mean = float(np.mean(np.abs(f_cold)))
        flux_sym = abs(fh_mean - fc_mean) / fh_mean if fh_mean else math.inf

        # TotEng drift over steady-state windows (40-50% vs 90-100%)
        n = len(toteng)
        a = int(0.4 * n)
        b = int(0.5 * n)
        e_a = float(np.mean(toteng[a:b])) if b > a else float(toteng[0])
        e_b = float(np.mean(toteng[int(0.9 * n):]))
        drift_rel = abs(e_b - e_a) / abs(e_a) if e_a != 0 else math.inf

        t_first = float(np.mean(temp[: max(1, int(0.1 * n))]))
        t_last = float(np.mean(temp[int(0.9 * n):]))

        blocks = parse_profile(prof_path)
        tail_frac = float(params.get("quality", {}).get("profile_tail_fraction", 0.2))
        cut = nprod * (1.0 - tail_frac)
        tail = [bl for bl in blocks if bl["step"] >= cut]
        if not tail:
            raise ParseError(f"没有 step>={cut:.0f} 的 profile 块（Nfreq 过小或日志截断）")
        z, t, cnt = average_blocks(tail)

        q = float(params["flux_ev_per_ps"]) * float(params["units"]["ev_per_ps_to_W"]) / (
            area * float(params["units"]["ang2_to_m2"])
        )
        tbr = compute_tbr(z, t, geom, q, th)

        # time convergence from profile halves
        half_blocks = [bl for bl in blocks if bl["step"] <= nprod * 0.5]
        half_blocks2 = [bl for bl in blocks if bl["step"] > nprod * 0.5]
        conv = None
        if half_blocks and half_blocks2:
            try:
                z1, t1, _ = average_blocks(half_blocks)
                z2, t2, _ = average_blocks(half_blocks2)
                v1 = compute_tbr(z1, t1, geom, q, th)["tbr_total_m2KW"]
                v2 = compute_tbr(z2, t2, geom, q, th)["tbr_total_m2KW"]
                conv = {
                    "tbr_first_half_m2KW": v1,
                    "tbr_second_half_m2KW": v2,
                    "rel_diff": abs(v1 - v2) / abs(v2) if v2 else math.inf,
                }
            except ParseError:
                conv = None

        result.update(
            {
                "status": "OK",
                "lammps_banner": text.splitlines()[0].strip() if text.splitlines() else "",
                "box": {"lx": lx, "ly": ly, "area_A2": area, "projected": geom["box"]},
                "q_W_m2": q,
                "counts": {"hot": nhot, "cold": ncold},
                "energy": {
                    "flux_hot_eVps": fh_mean,
                    "flux_cold_eVps": fc_mean,
                    "flux_symmetry_rel": flux_sym,
                    "toteng_mean_eV": float(np.mean(toteng)),
                    "toteng_drift_rel": drift_rel,
                },
                "temperature": {
                    "mean_first10pct_K": t_first,
                    "mean_last10pct_K": t_last,
                    "drift_K": t_last - t_first,
                },
                "profile": {
                    "n_blocks_total": len(blocks),
                    "n_blocks_used": len(tail),
                    "n_chunks": int(len(z)),
                    "n_chunks_occupied": int(np.isfinite(t).sum()),
                    "z_first_A": float(z[0]),
                    "z_last_A": float(z[-1]),
                    "T_min_K": float(np.nanmin(t)),
                    "T_max_K": float(np.nanmax(t)),
                    "T_span_K": float(np.nanmax(t) - np.nanmin(t)),
                },
                "dT_total_K": tbr["dT_total_K"],
                "tbr_total_m2KW": tbr["tbr_total_m2KW"],
                "tbr_iface_mean_m2KW": tbr["tbr_iface_mean_m2KW"],
                "interfaces": tbr["interfaces"],
                "time_convergence": conv,
                "checks": {
                    "log_complete": "Total wall time" in text,
                    "lost_atoms": "Lost atoms" in text,
                    "minimize_criterion": (CRIT_RE.search(text).group(1).strip()
                                           if CRIT_RE.search(text) else None),
                    "exit_code": seed_meta.get("exit_code"),
                },
            }
        )
    except ParseError as exc:
        result.update({"status": "PARSE_ERROR", "error": str(exc)})
        geomlib.dump_json(seed_dir / "result.json", result)
        print(f"[POST][FAIL] {args.seed}: {exc}", file=sys.stderr)
        return 2

    geomlib.dump_json(seed_dir / "result.json", result)
    print(
        f"[POST] {run_dir.name}/{args.seed} dT_total={result['dT_total_K']:.3f} K "
        f"TBR={result['tbr_total_m2KW']:.4e} m2K/W q={q:.4e} W/m2"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
