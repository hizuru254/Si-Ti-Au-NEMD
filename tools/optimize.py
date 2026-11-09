#!/usr/bin/env python3
"""Surrogate optimizer: read passed runs, propose the next scan points.

Policy
  * <5 valid points  -> space-filling Latin hypercube (exploration)
  * >=5 valid points -> GP (RBF) on log10(TBR) + Expected Improvement
  * only is_passed=True rows are used; failed rows are ignored
  * proposals are written as a new scan CSV with status=pending; nothing runs here

Exit codes: 0 ok, 2 not enough data/config.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geomlib  # noqa: E402

KINDS = ["rect", "trapezoid", "cross", "rot45"]
SIDED = ["single", "double"]


def load_space(path: Path) -> dict:
    return geomlib.load_json(path)


def load_rows(summary: Path) -> list[dict]:
    if not summary.exists():
        return []
    with open(summary, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def encode(row: dict, space: dict) -> np.ndarray | None:
    kind = (row.get("kind") or "rect").strip()
    if kind not in KINDS:
        return None
    vec = []
    for k in KINDS:
        vec.append(1.0 if kind == k else 0.0)
    for key in ("W_nm", "D_nm", "P_nm", "t_nm", "phi_deg"):
        lo, hi = float(space[key][0]), float(space[key][1])
        v = float(row.get(key) or 0)
        vec.append((v - lo) / (hi - lo) if hi > lo else 0.0)
    vec.append(1.0 if (row.get("sided") or "single") == "double" else 0.0)
    return np.array(vec, dtype=float)


def decode(x: np.ndarray, space: dict) -> dict:
    kind = KINDS[int(np.argmax(x[:4]))]
    vals = {}
    for i, key in enumerate(("W_nm", "D_nm", "P_nm", "t_nm", "phi_deg")):
        lo, hi = float(space[key][0]), float(space[key][1])
        vals[key] = round(lo + float(x[4 + i]) * (hi - lo), 3)
    vals["kind"] = kind
    vals["sided"] = "double" if x[9] >= 0.5 else "single"
    if kind in ("trapezoid", "cross"):
        vals["phi_deg"] = 0.0
    return vals


def valid(v: dict, space: dict) -> bool:
    if v["P_nm"] <= v["W_nm"]:
        return False
    if v["D_nm"] * 10.0 > float(space.get("max_D_A", 8.0)) + 1e-9:
        return False
    return True


def lhs(n: int, space: dict, rng: np.random.Generator) -> list[dict]:
    d = 10
    u = np.empty((n, d))
    for j in range(d):
        u[:, j] = (rng.permutation(n) + rng.random(n)) / n
    out = []
    tries = 0
    while len(out) < n and tries < n * 400:
        tries += 1
        row = u[len(out) % n].copy()
        row[:4] = 0.0
        row[int(rng.integers(0, 4))] = 1.0
        row[9] = 1.0 if rng.random() < 0.5 else 0.0
        v = decode(row, space)
        if valid(v, space):
            out.append(v)
    return out


def rbf(A: np.ndarray, B: np.ndarray, l: float) -> np.ndarray:
    d2 = ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1)
    return np.exp(-0.5 * d2 / (l * l))


def gp_fit(X: np.ndarray, y: np.ndarray, noise: float = 1e-3):
    best = None
    for l in (0.15, 0.25, 0.4, 0.6, 0.9, 1.4, 2.0):
        K = rbf(X, X, l) + noise * np.eye(len(X))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            continue
        alpha = np.linalg.solve(L.T, np.linalg.solve(L, y))
        lml = -0.5 * float(y @ alpha) - float(np.log(np.diag(L)).sum()) \
            - 0.5 * len(X) * math.log(2 * math.pi)
        if best is None or lml > best[0]:
            best = (lml, l, K, alpha)
    if best is None:
        raise RuntimeError("GP 拟合失败")
    return best[1], best[2], best[3]


def gp_predict(Xs: np.ndarray, X: np.ndarray, K: np.ndarray, alpha: np.ndarray,
               l: float) -> tuple[np.ndarray, np.ndarray]:
    Ks = rbf(Xs, X, l)
    mu = Ks @ alpha
    v = np.linalg.solve(K, Ks.T)
    var = 1.0 - np.einsum("ij,ji->i", Ks, v)
    return mu, np.maximum(var, 1e-12)


def phi(z: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def Phi(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default="workspace/scan_summary.csv")
    ap.add_argument("--space", default="config/search_space.json")
    ap.add_argument("--scan-csv", default="config/scan.csv")
    ap.add_argument("--out", default="config/scan.next.csv")
    ap.add_argument("--n-propose", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    space = load_space(Path(args.space))
    rows = load_rows(Path(args.summary))
    data = []
    for r in rows:
        if (r.get("is_passed") or "").strip() != "True":
            continue
        try:
            tbr = float(r.get("TBR_mean") or "nan")
        except ValueError:
            continue
        x = encode(r, space)
        if x is None or not math.isfinite(tbr) or tbr <= 0:
            continue
        data.append((r, x, tbr))

    if data:
        data.sort(key=lambda t: t[2])
        print(f"[OPT] valid points: {len(data)}  best TBR={data[0][2]:.4e}")
        print(f"{'scan_id':<10}{'kind':<11}{'W':>6}{'D':>6}{'P':>7}{'t':>6}{'sided':>8}{'TBR':>12}")
        for r, _, tbr in data[:args.top]:
            print(f"{r.get('scan_id',''):<10}{r.get('kind',''):<11}"
                  f"{float(r.get('W_nm') or 0):>6.2f}{float(r.get('D_nm') or 0):>6.2f}"
                  f"{float(r.get('P_nm') or 0):>7.2f}{float(r.get('t_nm') or 0):>6.2f}"
                  f"{r.get('sided',''):>8}{tbr:>12.3e}")

    rng = np.random.default_rng(args.seed)
    if len(data) < 5:
        proposals = lhs(args.n_propose, space, rng)
        method = f"LHS (n_valid={len(data)} < 5)"
    else:
        X = np.vstack([d[1] for d in data])
        y = np.log10(np.array([d[2] for d in data]))
        Xm, Xs = X.mean(0), X.std(0) + 1e-9
        ym, ys = y.mean(), y.std() + 1e-9
        Xn, yn = (X - Xm) / Xs, (y - ym) / ys
        l, K, alpha = gp_fit(Xn, yn)
        pool = lhs(4000, space, rng)
        Xp = np.vstack([encode(p, space) for p in pool])
        Xpn = (Xp - Xm) / Xs
        mu, var = gp_predict(Xpn, Xn, K, alpha, l)
        sigma = np.sqrt(var)
        best = float(yn.min())
        z = (best - mu - 0.01) / sigma
        ei = (best - mu - 0.01) * Phi(z) + sigma * phi(z)
        order = np.argsort(-ei)
        proposals = []
        for idx in order:
            p = pool[int(idx)]
            if all(np.linalg.norm(encode(p, space) - encode(q, space)) > 0.06
                   for q in proposals):
                proposals.append(p)
            if len(proposals) >= args.n_propose:
                break
        method = f"GP+EI (n_valid={len(data)}, l={l:.2f})"

    # next scan ids
    existing = set()
    scan_csv = Path(args.scan_csv)
    if scan_csv.exists():
        with open(scan_csv, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                m = row.get("scan_id", "")
                if m.startswith("S") and m[1:].isdigit():
                    existing.add(int(m[1:]))
    nxt = max(existing) + 1 if existing else 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scan_id", "kind", "W_nm", "D_nm", "P_nm", "t_nm",
                    "phi_deg", "sided", "status", "note"])
        for p in proposals:
            w.writerow([f"S{nxt:03d}", p["kind"], p["W_nm"], p["D_nm"], p["P_nm"],
                        p["t_nm"], p["phi_deg"], p["sided"], "pending",
                        f"proposed by optimize.py | {method}"])
            nxt += 1
    print(f"[OPT] {method}")
    print(f"[OPT] wrote {len(proposals)} proposals -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
