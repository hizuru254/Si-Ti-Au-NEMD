"""Shared helpers for the si_nemd agent toolkit.

Only standard library + numpy (postprocess).  Keep this module dependency-free
so preflight can run before numpy is confirmed available.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")


# --------------------------------------------------------------------------- #
# paths / config
# --------------------------------------------------------------------------- #
def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def dump_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def resolve_project_root(config_path: Path, params: dict) -> Path:
    raw = params.get("project_root", "..")
    root = (config_path.parent / raw).resolve() if not os.path.isabs(raw) else Path(raw)
    return root


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def free_gb(path: Path) -> float:
    anchor = Path(path.anchor or path)
    try:
        usage = os.statvfs(anchor)  # type: ignore[attr-defined]
        return usage.f_bavail * usage.f_frsize / 1e9
    except AttributeError:
        import shutil

        return shutil.disk_usage(str(anchor)).free / 1e9


# --------------------------------------------------------------------------- #
# LAMMPS data file header
# --------------------------------------------------------------------------- #
def read_data_header(path: Path) -> dict:
    info = {
        "path": str(path),
        "n_atoms": None,
        "n_types": None,
        "box": {},
        "triclinic": False,
        "first_line": "",
    }
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = [fh.readline() for _ in range(40)]
    info["first_line"] = lines[0].strip()
    num = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
    for line in lines:
        s = line.strip()
        m = re.match(r"^(\d+)\s+atoms\s*$", s)
        if m:
            info["n_atoms"] = int(m.group(1))
        m = re.match(r"^(\d+)\s+atom\s+types\s*$", s)
        if m:
            info["n_types"] = int(m.group(1))
        m = re.match(rf"^({num})\s+({num})\s+xlo\s+xhi\s*$", s)
        if m:
            info["box"]["xlo"], info["box"]["xhi"] = float(m.group(1)), float(m.group(2))
        m = re.match(rf"^({num})\s+({num})\s+ylo\s+yhi\s*$", s)
        if m:
            info["box"]["ylo"], info["box"]["yhi"] = float(m.group(1)), float(m.group(2))
        m = re.match(rf"^({num})\s+({num})\s+zlo\s+zhi\s*$", s)
        if m:
            info["box"]["zlo"], info["box"]["zhi"] = float(m.group(1)), float(m.group(2))
        m = re.match(rf"^({num})\s+({num})\s+({num})\s+xy\s+xz\s+yz\s*$", s)
        if m:
            info["triclinic"] = True
    return info


# --------------------------------------------------------------------------- #
# atom counting (needs the real structure)
# --------------------------------------------------------------------------- #
def count_atoms_by_z(path: Path, ranges: dict[str, tuple[float, float]]) -> dict[str, int]:
    """Count atoms whose z lies in each [lo, hi] range (upper bound exclusive).

    Reads only the Atoms section of an atom_style atomic data file:
        id type x y z [ix iy iz]
    """
    counts = {k: 0 for k in ranges}
    in_atoms = False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                if in_atoms and counts:
                    continue
                continue
            low = s.lower()
            if not in_atoms:
                if low.startswith("atoms"):
                    in_atoms = True
                continue
            if low.startswith(("velocities", "masses", "bond", "angle", "pair",
                               "improper", "dihedral")):
                break
            parts = s.split()
            if len(parts) < 5 or parts[0].startswith("#"):
                continue
            try:
                z = float(parts[4])
            except ValueError:
                continue
            for name, (lo, hi) in ranges.items():
                if lo <= z < hi:
                    counts[name] += 1
    return counts


# --------------------------------------------------------------------------- #
# geometry validation
# --------------------------------------------------------------------------- #
def _close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def validate_geom(geom: dict, thresholds: dict, allow_draft: bool = False,
                  bin_a: float | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if geom.get("schema_version") != "1.0":
        errors.append("geom.schema_version 必须为 '1.0'")
    status = geom.get("status", "DRAFT")
    if status != "APPROVED" and not allow_draft:
        errors.append(f"geom.status={status}；未获人类批准（APPROVED）不得启动计算")

    box = geom.get("box", {})
    try:
        lx, ly = float(box["lx"]), float(box["ly"])
        zmin, zmax = float(box["z_min"]), float(box["z_max"])
    except (KeyError, TypeError, ValueError):
        errors.append("geom.box 缺少 lx/ly/z_min/z_max 或不是数值")
        lx = ly = 0.0
        zmin, zmax = 0.0, 0.0
    if lx <= 0 or ly <= 0:
        errors.append("geom.box.lx/ly 必须为正")
    if zmax <= zmin:
        errors.append("geom.box.z_max 必须大于 z_min")
    if box.get("boundary", "p p p") != "p p p":
        warnings.append("boundary 非 'p p p'：周期性假设与热流面积公式可能不成立")

    layers = geom.get("layers") or []
    if not layers:
        errors.append("geom.layers 不能为空")
    mats = []
    prev_top = None
    for i, layer in enumerate(layers):
        try:
            lo, hi = float(layer["z_min"]), float(layer["z_max"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"layers[{i}] 缺少 z_min/z_max")
            continue
        if hi <= lo:
            errors.append(f"layers[{i}] ({layer.get('id')}) 厚度必须为正")
        if prev_top is not None and not _close(prev_top, lo):
            errors.append(
                f"layers[{i}] ({layer.get('id')}) 与上一层不连续：上一层顶 {prev_top} != 本层底 {lo}"
            )
        prev_top = hi
        mats.append((layer.get("material"), lo, hi, layer.get("id")))

    if mats:
        stack_lo, stack_hi = mats[0][1], mats[-1][2]
        if zmin > stack_lo + 1e-6 or zmax < stack_hi - 1e-6:
            errors.append(
                f"box.z {zmin}..{zmax} 未包含整个叠层 {stack_lo}..{stack_hi}"
            )
        boundary = box.get("boundary", "p p p")
        if boundary != "p p p":
            errors.append("当前模板固定 boundary p p p；其他边界条件需先改模板并重新验证")
        vacuum = (stack_lo - zmin) + (zmax - stack_hi)
        if vacuum < 5.0:
            errors.append(
                f"叠层两端真空余量合计仅 {vacuum:.2f} Å（要求 >=5 Å）。"
                "p p p 下热源与热汇会在周期边界直接相邻，热流绕过叠层。"
            )

    def material_at(z: float):
        for m, lo, hi, lid in mats:
            if lo - 1e-6 <= z <= hi + 1e-6:
                return m, lo, hi, lid
        return None

    interfaces = geom.get("interfaces") or []
    if not interfaces:
        errors.append("geom.interfaces 不能为空")
    min_w = float(thresholds.get("fit_window_min_A", 6.0))
    min_pts = int(thresholds.get("fit_min_points", 4))
    bin_a = float(bin_a if bin_a is not None else geom.get("chunk_bin_A", 2.0))
    zs = []
    for k, itf in enumerate(interfaces):
        name = itf.get("id", f"iface{k}")
        try:
            z = float(itf["z"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"界面 {name} 缺少 z")
            continue
        zs.append(z)
        hit = material_at(z)
        if hit is None:
            errors.append(f"界面 {name} z={z} 不在任何层内")
            continue
        if not _close(z, hit[1]) and not _close(z, hit[2]):
            errors.append(f"界面 {name} z={z} 不是层边界（最近的层 {hit[3]} 为 {hit[1]}..{hit[2]}）")
        for side in ("left", "right"):
            win = itf.get(side) or {}
            try:
                wlo, whi = float(win["z_min"]), float(win["z_max"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"界面 {name}.{side} 缺少 z_min/z_max")
                continue
            if whi <= wlo:
                errors.append(f"界面 {name}.{side} 窗口上下界颠倒")
                continue
            width = whi - wlo
            if width < min_w:
                errors.append(
                    f"界面 {name}.{side} 窗口宽度 {width:.2f} Å < 最小 {min_w:.1f} Å"
                )
            if width / bin_a < min_pts:
                errors.append(
                    f"界面 {name}.{side} 窗口仅 {width / bin_a:.1f} 个 bin < 最小 {min_pts} 点"
                )
            # window must lie inside the declared material slab on that side
            target = None
            if side == "left":
                target = hit
            else:
                for m, lo, hi, lid in mats:
                    if _close(lo, z):
                        target = (m, lo, hi, lid)
                        break
            if target is None:
                errors.append(f"界面 {name}.{side} 找不到相邻层")
                continue
            m, lo, hi, lid = target
            declared = win.get("material")
            if declared and declared != m:
                errors.append(f"界面 {name}.{side} 声明材料 {declared} 与层 {lid} 材料 {m} 不符")
            if wlo < lo - 1e-6 or whi > hi + 1e-6:
                errors.append(
                    f"界面 {name}.{side} 窗口 {wlo}..{whi} 超出材料层 {lid} ({lo}..{hi})；"
                    "线性拟合会跨材料，结果无效"
                )
            for other in interfaces:
                try:
                    zo = float(other["z"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not _close(zo, z) and wlo < zo < whi:
                    errors.append(f"界面 {name}.{side} 窗口跨越了另一界面 z={zo}")
            for gname in ("hot", "cold"):
                g = (geom.get("groups") or {}).get(gname) or {}
                try:
                    glo, ghi = float(g["z_min"]), float(g["z_max"])
                except (KeyError, TypeError, ValueError):
                    continue
                if wlo < ghi and whi > glo:
                    errors.append(
                        f"界面 {name}.{side} 窗口 {wlo}..{whi} 与 {gname} 控温区 "
                        f"{glo}..{ghi} 重叠：控温区不能用于拟合"
                    )

    for a in range(len(zs)):
        for b in range(a + 1, len(zs)):
            if _close(zs[a], zs[b]):
                errors.append(f"界面 z 重复：{zs[a]}")

    groups = geom.get("groups") or {}
    hot, cold = groups.get("hot"), groups.get("cold")
    for gname, g in (("hot", hot), ("cold", cold)):
        if not isinstance(g, dict):
            errors.append(f"geom.groups.{gname} 缺失")
            continue
        try:
            glo, ghi = float(g["z_min"]), float(g["z_max"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"geom.groups.{gname} 缺少 z_min/z_max")
            continue
        if ghi <= glo:
            errors.append(f"geom.groups.{gname} 上下界颠倒")
        if mats and (glo < mats[0][1] - 1e-6 or ghi > mats[-1][2] + 1e-6):
            errors.append(
                f"geom.groups.{gname} 必须落在叠层 {mats[0][1]}..{mats[-1][2]} 内（不能落在真空里）"
            )
    if isinstance(hot, dict) and isinstance(cold, dict):
        try:
            th = float(hot["z_max"]) - float(hot["z_min"])
            tc = float(cold["z_max"]) - float(cold["z_min"])
            if abs(th - tc) > 1e-6:
                warnings.append(
                    f"热源厚度 {th:.2f} Å 与热汇厚度 {tc:.2f} Å 不等：净热流不为零，需人工确认"
                )
        except (KeyError, TypeError, ValueError):
            pass

    return {
        "errors": errors,
        "warnings": warnings,
        "status": status,
        "n_interfaces": len(interfaces),
        "n_layers": len(layers),
        "lx": lx,
        "ly": ly,
        "z_min": zmin,
        "z_max": zmax,
        "area_A2": lx * ly,
    }


# --------------------------------------------------------------------------- #
# template tokens
# --------------------------------------------------------------------------- #
def template_tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text))
