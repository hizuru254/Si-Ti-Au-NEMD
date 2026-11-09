#!/usr/bin/env python3
"""Design-preview structures: Si/Ti/Au/Ti/Si with a patterned Si substrate.

Generates LAMMPS data files (atom_style atomic) plus PNG previews for OVITO.
These are INITIAL SHAPES ONLY: not minimised, not equilibrated, no potentials.
Use them to judge the pattern, not to publish numbers.

Stack (bottom -> top), symmetric:
  Si substrate  z in [-60, -30]   (grooves etched down from z = -30)
  Ti adhesion   one monolayer on the Si surface (preview simplification)
  Au film       fills grooves and continues to z = 20 - 2.5
  Ti adhesion   one monolayer under the top Si
  Si cap        z in [20, 30]     (double-sided variant grooves up from z = 20)

Conventions
  x,y in [0, L], L = 65.16 A  (12 x Si 5.43 = 16 x Au 4.0725)
  type 1 = Si (diamond), type 2 = Ti (monolayer), type 3 = Au (fcc)

Usage
  python tools/build_shapes.py --out shapes
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np

L = 65.16
A_SI = 5.43
A_AU = 4.0725
Z_SI_LO = -60.0
Z_SI_TOP = -30.0
Z_SI_R_BOT = 20.0
Z_SI_R_TOP = 30.0
T_AU = 44.0          # nominal Au film thickness above the flat Si top
TI_GAP = 2.5         # Au starts/ends this far from the Si surface

SI_BASIS = [
    (0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
    (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25),
]
AU_BASIS = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0)]

SHAPES = [
    dict(id="S0_flat",      label="flat baseline",            P=0.0,   W=0.0,   D=0.0,  side="single", phi=0.0,  kind="flat"),
    dict(id="S1_rect",      label="rectangular W16.3 D8 P32.6", P=32.58, W=16.29, D=8.0,  side="single", phi=0.0,  kind="rect"),
    dict(id="S2_deep",      label="deep narrow W8.1 D14 P32.6",  P=32.58, W=8.145, D=14.0, side="single", phi=0.0,  kind="rect"),
    dict(id="S3_trapezoid", label="trapezoid W20 D5 60deg",      P=32.58, W=20.0,  D=5.0,  side="single", phi=0.0,  kind="trapezoid"),
    dict(id="S4_double",    label="double-sided W16.3 D8",       P=32.58, W=16.29, D=8.0,  side="double", phi=0.0,  kind="rect"),
    dict(id="S5_rot45",     label="rotated 45deg W16.3 D8",      P=32.58, W=16.29, D=8.0,  side="single", phi=45.0, kind="rect"),
    dict(id="S6_cross",     label="crossed trenches W12 D8",     P=32.58, W=12.0,  D=8.0,  side="single", phi=0.0,  kind="cross"),
]


def build_lattice(a: float, basis, z_lo: float, z_hi: float) -> np.ndarray:
    n = int(round(L / a))
    assert abs(L - n * a) < 1e-6, (L, a)
    nz_lo = math.floor((z_lo - 1.0) / a) - 1
    nz_hi = math.ceil((z_hi + 1.0) / a) + 1
    g = np.arange(n) * a
    X, Y = np.meshgrid(g, g, indexing="xy")
    coords = []
    for k in range(nz_lo, nz_hi + 1):
        for bx, by, bz in basis:
            z = (k + bz) * a
            if not (z_lo - 1e-6 <= z <= z_hi + 1e-6):
                continue
            x = (X + bx * a).ravel() % L
            y = (Y + by * a).ravel() % L
            coords.append(np.column_stack([x, y, np.full(x.size, z)]))
    return np.vstack(coords)


def groove_depth(x: np.ndarray, y: np.ndarray, sh: dict) -> np.ndarray:
    """Depth of the etched groove below the nominal Si surface (0..D)."""
    kind = sh["kind"]
    if kind == "flat":
        return np.zeros_like(x, dtype=float)
    if kind == "rect":
        if sh["phi"] == 0.0:
            d = np.mod(x, sh["P"])
        elif sh["phi"] == 90.0:
            d = np.mod(y, sh["P"])
        else:
            ang = math.radians(sh["phi"])
            d = np.mod(x * math.cos(ang) + y * math.sin(ang), sh["P"])
        return np.where(d < sh["W"], sh["D"], 0.0)
    if kind == "cross":
        gx = np.mod(x, sh["P"]) < sh["W"]
        gy = np.mod(y, sh["P"]) < sh["W"]
        return np.where(gx | gy, sh["D"], 0.0)
    if kind == "trapezoid":
        d = np.abs(np.mod(x, sh["P"]) - sh["P"] / 2.0)
        half = sh["W"] / 2.0
        tan_a = math.tan(math.radians(60.0))
        return np.clip((half - d) / tan_a, 0.0, sh["D"])
    raise ValueError(kind)


def ti_monolayer(z_surface: np.ndarray, spacing: float = 2.85) -> np.ndarray:
    n = int(math.ceil(L / spacing))
    g = (np.arange(n) + 0.5) * (L / n)
    X, Y = np.meshgrid(g, g, indexing="xy")
    # z_surface is a function of (x,y); sample it on the same grid
    zs = z_surface(X, Y)
    return np.column_stack([X.ravel(), Y.ravel(), zs.ravel()])


def remove_close(frame: np.ndarray, other: np.ndarray, cutoff: float, box: float) -> np.ndarray:
    if len(other) == 0:
        return np.arange(len(frame))
    keep = np.ones(len(frame), dtype=bool)
    c2 = cutoff * cutoff
    for i in range(0, len(frame), 200):
        p = frame[i:i + 200][:, None, :]
        d = p - other[None, :, :]
        d[:, :, 0] -= box * np.round(d[:, :, 0] / box)
        d[:, :, 1] -= box * np.round(d[:, :, 1] / box)
        dist2 = np.einsum("ijk,ijk->ij", d, d)
        keep[i:i + 200] = ~(dist2 < c2).any(axis=1)
    return np.nonzero(keep)[0]


def build_shape(sh: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    # bottom Si substrate, grooves down from z = Z_SI_TOP
    si_l = build_lattice(A_SI, SI_BASIS, Z_SI_LO, Z_SI_TOP)
    d_l = groove_depth(si_l[:, 0], si_l[:, 1], sh)
    z_sl = Z_SI_TOP - d_l
    si_l = si_l[si_l[:, 2] <= z_sl + 1e-6]

    # top Si cap, grooves up from z = Z_SI_R_BOT for the double-sided variant
    si_r = build_lattice(A_SI, SI_BASIS, Z_SI_R_BOT, Z_SI_R_TOP)
    d_r = groove_depth(si_r[:, 0], si_r[:, 1], sh) if sh["side"] == "double" else np.zeros(len(si_r))
    z_sr = Z_SI_R_BOT + d_r
    si_r = si_r[si_r[:, 2] >= z_sr - 1e-6]

    # Ti monolayers on both Si surfaces
    def zsl_fn(x, y):
        return Z_SI_TOP - groove_depth(x, y, sh)

    def zsr_fn(x, y):
        if sh["side"] == "double":
            return Z_SI_R_BOT + groove_depth(x, y, sh)
        return np.full_like(x, Z_SI_R_BOT, dtype=float)

    ti_l = ti_monolayer(lambda X, Y: zsl_fn(X, Y) + 1.4)
    ti_r = ti_monolayer(lambda X, Y: zsr_fn(X, Y) - 1.4)
    ti_l = ti_l[remove_close(ti_l, si_l, 1.6, L)]
    ti_r = ti_r[remove_close(ti_r, si_r, 1.6, L)]

    # Au fills the grooves and forms the film between the two Ti layers
    au = build_lattice(A_AU, AU_BASIS, Z_SI_LO + 2.0, Z_SI_R_TOP - 2.0)
    zs_l = zsl_fn(au[:, 0], au[:, 1])
    zs_r = zsr_fn(au[:, 0], au[:, 1])
    au = au[(au[:, 2] >= zs_l + TI_GAP) & (au[:, 2] <= zs_r - TI_GAP)]
    au = au[remove_close(au, si_l, 1.7, L)]
    au = au[remove_close(au, si_r, 1.7, L)]
    au = au[remove_close(au, ti_l, 1.5, L)]
    au = au[remove_close(au, ti_r, 1.5, L)]
    au = au[remove_close(au, si_l, 1.7, L)]

    atoms = np.vstack([si_l, ti_l, au, ti_r, si_r])
    types = np.concatenate([
        np.ones(len(si_l), dtype=int),
        np.full(len(ti_l), 2, dtype=int),
        np.full(len(au), 3, dtype=int),
        np.full(len(ti_r), 2, dtype=int),
        np.ones(len(si_r), dtype=int),
    ])
    meta = {
        "n_si_l": len(si_l), "n_ti_l": len(ti_l), "n_au": len(au),
        "n_ti_r": len(ti_r), "n_si_r": len(si_r),
        "z_top": Z_SI_TOP, "z_bot": Z_SI_R_BOT,
    }
    return atoms, types, meta


def write_data(path: Path, atoms: np.ndarray, types: np.ndarray) -> None:
    zlo, zhi = Z_SI_LO - 5.0, Z_SI_R_TOP + 5.0
    lines = [
        "LAMMPS data file: Si/Ti/Au/Ti/Si patterned substrate (design preview)",
        "",
        f"{len(atoms)} atoms",
        "3 atom types",
        "",
        f"0.0 {L:.6f} xlo xhi",
        f"0.0 {L:.6f} ylo yhi",
        f"{zlo:.6f} {zhi:.6f} zlo zhi",
        "",
        "Masses",
        "",
        "1 28.0855",
        "2 47.867",
        "3 196.96657",
        "",
        "Atoms # atomic",
        "",
    ]
    for i, ((x, y, z), ty) in enumerate(zip(atoms, types), 1):
        lines.append(f"{i} {ty} {x:.6f} {y:.6f} {z:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# preview rendering (PIL only)
# --------------------------------------------------------------------------- #
COLORS = {1: (74, 126, 190), 2: (168, 173, 184), 3: (212, 175, 55)}


def render(path: Path, atoms: np.ndarray, types: np.ndarray, sh: dict, meta: dict) -> None:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1500, 780
    img = Image.new("RGB", (W, H), (16, 18, 22))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
        small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 16)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
        small = font

    gap = 28
    panel_w = (W - 3 * gap) // 2
    panel_h = H - 140
    y0 = 92

    # ---------------- left: schematic cross-section --------------------------
    x0 = gap
    zmin, zmax = Z_SI_LO - 2.0, Z_SI_R_TOP + 2.0
    s = min(panel_w / L, panel_h / (zmax - zmin))
    ox = x0 + (panel_w - L * s) / 2
    oz = y0 + (panel_h - (zmax - zmin) * s) / 2
    draw.text((x0, 60), f"{sh['id']}  cross-section Si/Ti/Au/Ti/Si", font=font,
              fill=(235, 235, 235))
    ncol = 620
    xs = np.linspace(0.0, L, ncol)
    ys = np.full_like(xs, 0.25 * sh["P"] if sh["P"] > 0 else L / 2)
    d_l = groove_depth(xs, ys, sh)
    z_sl = Z_SI_TOP - d_l
    if sh["side"] == "double":
        z_sr = Z_SI_R_BOT + groove_depth(xs, ys, sh)
    else:
        z_sr = np.full_like(xs, Z_SI_R_BOT)

    def zy(z):
        return oz + (zmax - z) * s

    for i in range(ncol):
        px = ox + xs[i] * s
        px2 = ox + (xs[i] + L / ncol) * s + 1
        draw.rectangle([px, zy(z_sl[i]), px2, zy(zmin)], fill=COLORS[1])
        draw.rectangle([px, zy(z_sl[i] + 2.0), px2, zy(z_sl[i])], fill=COLORS[2])
        draw.rectangle([px, zy(z_sr[i] - 2.0), px2, zy(z_sl[i] + 2.0)], fill=COLORS[3])
        draw.rectangle([px, zy(z_sr[i]), px2, zy(z_sr[i] - 2.0)], fill=COLORS[2])
        draw.rectangle([px, zy(zmax), px2, zy(z_sr[i])], fill=COLORS[1])

    # ---------------- right: depth map --------------------------------------
    x1 = gap * 2 + panel_w
    draw.text((x1, 60), f"{sh['id']}  groove depth map (x-y)", font=font,
              fill=(235, 235, 235))
    n = 320
    g = np.linspace(0.0, L, n)
    X, Y = np.meshgrid(g, g, indexing="xy")
    depth = groove_depth(X, Y, sh)
    frac = depth / max(sh["D"], 1e-9)
    dmap = Image.new("RGB", (n, n))
    px = dmap.load()
    c0 = np.array(COLORS[1], dtype=float)
    c1 = np.array(COLORS[3], dtype=float)
    for j in range(n):
        for i in range(n):
            f = float(np.clip(frac[j, i], 0.0, 1.0))
            c = (c0 * (1 - f) + c1 * f).astype(int)
            px[i, n - 1 - j] = tuple(int(v) for v in c)
    s2 = min(panel_w / L, panel_h / L)
    side = int(L * s2)
    dmap = dmap.resize((side, side), Image.LANCZOS)
    ox2 = int(x1 + (panel_w - side) / 2)
    oy2 = int(y0 + (panel_h - side) / 2)
    img.paste(dmap, (ox2, oy2))
    draw.text((ox2, oy2 + side + 4), "blue = Si surface, gold = deep groove",
              font=small, fill=(170, 170, 170))

    # ---------------- header / legend ---------------------------------------
    lx = gap
    for name, key in (("Si", 1), ("Ti", 2), ("Au", 3)):
        draw.rectangle([lx, 12, lx + 16, 28], fill=COLORS[key])
        draw.text((lx + 22, 10), name, font=small, fill=(220, 220, 220))
        lx += 62
    draw.text((W - 640, 10),
              f"P={sh['P']:.2f} A   W={sh['W']:.2f} A   D={sh['D']:.2f} A   "
              f"{sh['side']}   phi={sh['phi']:.0f} deg",
              font=small, fill=(205, 205, 205))
    draw.text((gap, H - 32),
              "design preview only: no minimisation, no potentials; "
              "Ti drawn as one monolayer (schematic 2 A band)",
              font=small, fill=(145, 145, 145))
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shapes")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for sh in SHAPES:
        atoms, types, meta = build_shape(sh)
        data = out / f"{sh['id']}.data"
        write_data(data, atoms, types)
        render(out / f"{sh['id']}.png", atoms, types, sh, meta)
        rows.append({
            "id": sh["id"], "label": sh["label"], "kind": sh["kind"],
            "P_A": sh["P"], "W_A": sh["W"], "D_A": sh["D"],
            "side": sh["side"], "phi_deg": sh["phi"],
            "n_atoms": len(atoms),
            "n_si": int((types == 1).sum()), "n_ti": int((types == 2).sum()),
            "n_au": int((types == 3).sum()),
            "file": data.name,
        })
        print(f"[SHAPE] {sh['id']:<12} atoms={len(atoms):>6}  Si={rows[-1]['n_si']:>5}  "
              f"Ti={rows[-1]['n_ti']:>4}  Au={rows[-1]['n_au']:>6}")

    with open(out / "shapes.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    try:
        from PIL import Image
        files = sorted(out.glob("S*.png"))
        cw, ch = 700, 364
        cols = 2
        grid = Image.new("RGB", (cw * cols, ch * ((len(files) + cols - 1) // cols)), (10, 12, 15))
        for i, f in enumerate(files):
            im = Image.open(f).convert("RGB").resize((cw, ch), Image.LANCZOS)
            grid.paste(im, ((i % cols) * cw, (i // cols) * ch))
        grid.save(out / "overview.png")
    except Exception as exc:  # noqa: BLE001
        print(f"[SHAPE] overview skipped: {exc}")

    readme = [
        "Si/Ti/Au/Ti/Si patterned substrate -- design preview",
        "=" * 56,
        "",
        "用途：在 OVITO 里直观比较几种刻槽/填充形状。这些是**初始形状**，",
        "没有做最小化、没有加势函数，不能用于任何数值结论。",
        "",
        "堆叠顺序（从下到上）：",
        "  Si 衬底 [-60,-30]  ->  Ti 粘附层（单层近似）->  Au 填槽+薄膜",
        "  ->  Ti 粘附层（单层近似）->  Si 顶盖 [20,30]",
        "  Ti 在预览中用一原子层表示（约 3 A），生产结构需要真实 Ti 层。",
        "",
        "坐标与类型：",
        f"  盒子 x,y = 0..{L} A；z = {Z_SI_LO - 5}..{Z_SI_R_TOP + 5}",
        "  类型 1 = Si（金刚石，a=5.43 A）",
        "  类型 2 = Ti（预览单层）",
        "  类型 3 = Au（fcc，a=4.0725 A）",
        "",
        "OVITO 使用：",
        "  File -> Open -> 选 S*.data",
        "  Add modifier -> Color coding -> Property = Particle Type",
        "  Si 蓝、Ti 灰、Au 金。",
        "  截面：Orthographic，沿 -y 看（x-z 面）。",
        "  看图案：Slice 掉 z > -29 的 Au/Ti/Si 顶盖，或直接看 PNG。",
        "",
        "形状清单（Au 薄膜名义厚度 44 A；P/W/D 单位 A）：",
    ]
    for r in rows:
        readme.append(
            f"  {r['id']:<12} {r['label']:<28} atoms={r['n_atoms']:<6} "
            f"P={r['P_A']} W={r['W_A']} D={r['D_A']} {r['side']} phi={r['phi_deg']}"
        )
    readme += [
        "",
        "设计意图（假设，待真实势函数验证）：",
        "  S0 平面：基准。",
        "  S1 矩形槽：增加 Si/Ti/Au 接触面积 + Au 嵌入。",
        "  S2 深窄槽：更高界面面积，但深宽比大，易出现填充空洞。",
        "  S3 梯形槽：60 度侧壁接近 Si 刻蚀面，应力集中较小。",
        "  S4 双面槽：上下两个 Si 界面同时图案化。",
        "  S5 45 度旋转：面内各向异性/声子失配调节。",
        "  S6 交叉槽：二维约束，界面面积最大，但可能形成孤立 Au 柱。",
        "",
        "注意：这些文件只用于看形状。生产用结构必须另行平衡，并通过 G0。",
    ]
    (out / "README_shapes.txt").write_text("\n".join(readme) + "\n", encoding="utf-8-sig")
    print(f"[SHAPE] wrote {out}/shapes.csv and {out}/README_shapes.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
