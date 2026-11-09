#!/usr/bin/env python3
"""
Summarize a Harbor job on LongBench v2 the way the official result.py does:
overall accuracy plus accuracy by difficulty (easy/hard) and length
(short/medium/long), and additionally by domain.

Unlike a naive mean over verifier outputs, this reports the trial accounting
explicitly:

  attempted  = trial directories in the job (one per task x attempt)
  scored     = trials whose verifier produced a reward
  failed     = attempted - scored, split into
               - trial exception (environment/agent/verifier crashed)
               - verifier ran but wrote no reward

Accuracy is reported two ways: over *scored* trials (what result.py would
compute from the predictions it was given) and over *attempted* trials with
failures counted as wrong (the conservative number).

Usage:
    python src/longbench-v2/scripts/summarize.py jobs/<job-id> [jobs/<job-id> ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect(job_dirs: list[Path]) -> tuple[list[dict], list[dict]]:
    """Return (scored_rows, failed_rows). Each row carries task metadata when known."""
    scored: list[dict] = []
    failed: list[dict] = []
    for job_dir in job_dirs:
        # A trial directory is one that holds a trial-level result.json next to a
        # config.json (Harbor's layout); rglob also covers a parent of several jobs.
        trial_dirs = sorted(
            {p.parent for p in job_dir.rglob("result.json") if (p.parent / "config.json").is_file() and p.parent != job_dir}
        )
        for trial_dir in trial_dirs:
            trial = _load_json(trial_dir / "result.json") or {}
            verifier = _load_json(trial_dir / "verifier" / "result.json")
            reward = None
            if verifier is not None and "reward" in verifier:
                reward = float(verifier["reward"])
            else:
                rewards = (trial.get("verifier_result") or {}).get("rewards") or {}
                if "reward" in rewards and rewards["reward"] is not None:
                    reward = float(rewards["reward"])
            meta = {
                "trial": trial_dir.name,
                "task_name": trial.get("task_name"),
                "domain": (verifier or {}).get("domain"),
                "difficulty": (verifier or {}).get("difficulty"),
                "length": (verifier or {}).get("length"),
                "status": (verifier or {}).get("status"),
            }
            if reward is None:
                exc = trial.get("exception_info") or {}
                meta["failure"] = (
                    f"exception: {exc.get('exception_type') or exc.get('type') or 'unknown'}"
                    if exc
                    else "verifier produced no reward"
                )
                failed.append(meta)
            else:
                meta["reward"] = reward
                scored.append(meta)
    return scored, failed


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    job_dirs = [Path(p) for p in sys.argv[1:]]
    scored, failed = collect(job_dirs)
    attempted = len(scored) + len(failed)
    if attempted == 0:
        raise SystemExit("No trials found (expected <job>/<trial>/result.json).")

    n_exc = sum(1 for f in failed if f["failure"].startswith("exception"))
    print(f"attempted trials : {attempted}")
    print(f"scored trials    : {len(scored)}")
    print(f"failed trials    : {len(failed)}  (trial exceptions: {n_exc}, verifier without reward: {len(failed) - n_exc})")
    if failed:
        print("  failed:")
        for f in failed:
            print(f"    {f['trial']:<48s} {f['failure']}")
    print()

    def acc(group: list[dict]) -> float:
        return sum(r["reward"] for r in group) / len(group) if group else float("nan")

    correct = sum(r["reward"] for r in scored)
    print(f"{'accuracy (scored)':<44s} n={len(scored):4d}  acc={100 * acc(scored):6.2f}%")
    print(f"{'accuracy (attempted, failures = 0)':<44s} n={attempted:4d}  acc={100 * correct / attempted:6.2f}%")
    for key in ("difficulty", "length", "domain"):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in scored:
            buckets[str(r.get(key))].append(r)
        for name in sorted(buckets):
            print(f"  {key + '=' + name:<42s} n={len(buckets[name]):4d}  acc={100 * acc(buckets[name]):6.2f}%")

    unparsed = sum(1 for r in scored if r.get("status") not in (None, "answered"))
    print(f"\nscored trials with unparseable/missing answers: {unparsed}")


if __name__ == "__main__":
    main()
