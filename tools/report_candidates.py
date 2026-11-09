#!/usr/bin/env python3
"""Human-facing candidate report: top-k PASSED runs by TBR, with audit links."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default="workspace/scan_summary.csv")
    ap.add_argument("--out", default="optimization/candidates.md")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    summary = Path(args.summary)
    if not summary.exists():
        print(f"[REPORT] no summary: {summary}")
        return 2
    with open(summary, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    valid = []
    for r in rows:
        if (r.get("is_passed") or "").strip() != "True":
            continue
        try:
            tbr = float(r.get("TBR_mean") or "nan")
        except ValueError:
            continue
        if tbr == tbr and tbr > 0:
            valid.append((tbr, r))
    valid.sort(key=lambda t: t[0])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ws = summary.parent
    lines = [
        "# 候选结构报告（自动生成）",
        "",
        f"- 数据：`{summary.as_posix()}`",
        f"- 通过 QC 的点：{len(valid)}",
        "- 排序：TBR_total 升序；只有 `is_passed=True` 的行参与排序。",
        "- 注意：这是**模型内最优**，不是实验值；Ti 为 hcp 几何 + LJ，",
        "  未含电子热导与硅化物化学。",
        "",
    ]
    if not valid:
        lines += ["当前没有通过 QC 的候选点。先解决锚点/门禁问题，不要在此排序。", ""]
    else:
        lines += [
            "| 排名 | scan_id | kind | W (nm) | D (nm) | P (nm) | t (nm) | sided | TBR (m²K/W) | relstd | 证据 |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for i, (tbr, r) in enumerate(valid[:args.top], 1):
            run_id = r.get("run_id", "")
            rel = (ws / run_id / "report.txt").as_posix()
            try:
                rel = Path(rel).relative_to(out.parent).as_posix()
            except ValueError:
                pass
            lines.append(
                f"| {i} | {r.get('scan_id','')} | {r.get('kind','')} | "
                f"{r.get('W_nm','')} | {r.get('D_nm','')} | {r.get('P_nm','')} | "
                f"{r.get('t_nm','')} | {r.get('sided','')} | {tbr:.3e} | "
                f"{r.get('TBR_relstd','')} | [report]({rel}) |"
            )
        lines += [
            "",
            "## 人工审核清单",
            "",
            "1. TBR 是否随接触面积增加而下降？",
            "2. W/D/P/t 的趋势是否连续，还是孤立低点？",
            "3. 候选点的 R²、时间收敛、relstd 是否贴边通过？",
            "4. 截面图里槽是否填满、有无空洞/悬空原子？",
            "5. TBR 是否在 1e-9–1e-8 的合理范围？",
            "6. 相对平面基准的降幅是否 >20%？",
            "",
        ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print(f"[REPORT] {len(valid)} passed points -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
