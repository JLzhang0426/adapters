#!/usr/bin/env python3
"""
LongBench v2 verifier.

Extracts the predicted letter from /app/answer.txt using the same logic as the
official `pred.py::extract_answer` (first "The correct answer is (X)", then
"The correct answer is X"), extended to accept a bare letter answer. Reward is
1.0 on an exact match with the gold letter, 0.0 otherwise (including no/invalid
answer, which the official `result.py` also counts as wrong in its default
uncompensated accuracy).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def extract_answer(response: str) -> str | None:
    """Mirror of THUDM/LongBench pred.py extract_answer, plus a bare-letter fallback."""
    response = response.replace("*", "")
    match = re.search(r"The correct answer is \(([A-D])\)", response)
    if match:
        return match.group(1)
    match = re.search(r"The correct answer is ([A-D])", response)
    if match:
        return match.group(1)
    stripped = response.strip()
    match = re.fullmatch(r"\(?([A-Da-d])\)?\.?", stripped)
    if match:
        return match.group(1).upper()
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answer-file", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--reward", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    gold = str(expected["answer"]).strip().upper()

    if args.answer_file.exists():
        raw = args.answer_file.read_text(encoding="utf-8", errors="replace")
        status = "answered"
    else:
        raw = ""
        status = "missing_answer_file"

    pred = extract_answer(raw) if raw.strip() else None
    if pred is None and status == "answered":
        status = "unparseable_answer"
    reward = 1.0 if pred == gold else 0.0

    result = {
        "status": status,
        "reward": reward,
        "pred": pred,
        "gold": gold,
        "raw_answer": raw[:2000],
        "source_id": expected.get("source_id"),
        "domain": expected.get("domain"),
        "sub_domain": expected.get("sub_domain"),
        "difficulty": expected.get("difficulty"),
        "length": expected.get("length"),
    }
    args.reward.parent.mkdir(parents=True, exist_ok=True)
    args.reward.write_text(str(reward), encoding="utf-8")
    args.result.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "raw_answer"}))


if __name__ == "__main__":
    main()
