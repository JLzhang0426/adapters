#!/usr/bin/env python3
"""
Summarize a Harbor job on LongBench v2 the way the official result.py does:
overall accuracy plus accuracy by difficulty (easy/hard) and length
(short/medium/long), and additionally by domain.

Usage:
    python src/longbench-v2/scripts/summarize.py jobs/<job-id> [jobs/<job-id> ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    rows: list[dict] = []
    for job_dir in map(Path, sys.argv[1:]):
        for result_path in job_dir.rglob("verifier/result.json"):
            try:
                rows.append(json.loads(result_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    if not rows:
        raise SystemExit("No verifier/result.json files found.")

    def report(label: str, group: list[dict]) -> None:
        acc = sum(float(r.get("reward", 0.0)) for r in group) / len(group)
        print(f"{label:<44s} n={len(group):4d}  acc={100 * acc:6.2f}%")

    report("overall", rows)
    for key in ("difficulty", "length", "domain"):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            buckets[str(r.get(key))].append(r)
        for name in sorted(buckets):
            report(f"  {key}={name}", buckets[name])
    unparsed = sum(1 for r in rows if r.get("status") != "answered")
    print(f"\nunparseable/missing answers: {unparsed}")


if __name__ == "__main__":
    main()
