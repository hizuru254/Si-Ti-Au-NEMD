#!/usr/bin/env python3
"""Change only the status column of one scan.csv row (atomic rewrite).

Allowed: pending -> running -> done|failed|skipped
Exit codes: 0 ok, 2 rejected.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

VALID = {
    "pending": {"running", "skipped"},
    "running": {"done", "failed", "skipped"},
    "done": set(),
    "failed": {"pending"},
    "skipped": {"pending"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-csv", required=True)
    ap.add_argument("--scan-id", required=True)
    ap.add_argument("--status", required=True)
    args = ap.parse_args()

    path = Path(args.scan_csv).resolve()
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    if not fields or "status" not in fields:
        print("[SCAN][FAIL] scan.csv 缺少 status 列", file=sys.stderr)
        return 2

    target = None
    for row in rows:
        if (row.get("scan_id") or "").strip() == args.scan_id:
            target = row
            break
    if target is None:
        print(f"[SCAN][FAIL] 找不到 scan_id={args.scan_id}", file=sys.stderr)
        return 2

    old = (target.get("status") or "").strip() or "pending"
    if args.status == old:
        print(f"[SCAN] {args.scan_id}: 已是 {old}，无改动")
        return 0
    if args.status not in VALID.get(old, set()):
        print(f"[SCAN][FAIL] 非法状态迁移: {old} -> {args.status}", file=sys.stderr)
        return 2

    target["status"] = args.status
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)
    print(f"[SCAN] {args.scan_id}: {old} -> {args.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
