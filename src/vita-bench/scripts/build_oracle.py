#!/usr/bin/env python3
"""
Collect oracle trajectories for the VitaBench adapter from Harbor job outputs.

VitaBench has no reference solutions (reward is a rubric-based LLM judge over
the conversation), so oracle solutions are built the way the adapter spec
describes for such benchmarks: run capable agents over the tasks, keep the
trajectories that score 1.0, then fill the remaining tasks with stronger
models / more trials under human review.

This script scans one or more Harbor `jobs/` directories, finds trials whose
verifier reward is 1.0, and copies the runtime state file
(`verifier/vita_runtime_state.json`, saved by the verifier) to `src/vita-bench/oracle/<task_set>/<id>.json`
so the adapter can ship it as `solution/oracle_trajectory.json`.

Usage (from the adapters repo root):

    python src/vita-bench/scripts/build_oracle.py jobs/<job-id> [jobs/<job-id> ...]
    python src/vita-bench/scripts/build_oracle.py jobs/<job-id> --min-passes 2

A trajectory is only accepted when it has been scored 1.0 at least
`--min-passes` times across the scanned trials (re-run the verifier with
`harbor run ... -a oracle` on the generated dataset to add confirmations), which
guards against single lucky judgments from the stochastic evaluator.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

ORACLE_DIR = Path(__file__).resolve().parents[1] / "oracle"


def _reward(trial_dir: Path) -> float | None:
    reward_path = trial_dir / "verifier" / "reward.txt"
    if not reward_path.exists():
        return None
    try:
        return float(reward_path.read_text().strip())
    except ValueError:
        return None


def _task_identity(state: dict) -> tuple[str, str] | None:
    task_set = state.get("task_set")
    task_id = state.get("task_id")
    if not task_set or not task_id:
        return None
    return str(task_set), str(task_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dirs", nargs="+", type=Path)
    parser.add_argument("--min-passes", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # (task_set, task_id) -> list of (passes, state_path)
    candidates: dict[tuple[str, str], list[tuple[int, Path]]] = defaultdict(list)
    pass_counts: dict[str, int] = defaultdict(int)

    for job_dir in args.job_dirs:
        for state_path in job_dir.rglob("verifier/vita_runtime_state.json"):
            trial_dir = state_path.parent.parent
            reward = _reward(trial_dir)
            if reward is None or reward < 1.0:
                continue
            state = json.loads(state_path.read_text(encoding="utf-8"))
            identity = _task_identity(state)
            if identity is None:
                continue
            if state.get("termination_reason") not in {"agent_stop", "user_stop"}:
                continue
            key = json.dumps(state["messages"], sort_keys=True, ensure_ascii=False)
            pass_counts[key] += 1
            candidates[identity].append((pass_counts[key], state_path))

    written = 0
    skipped: list[str] = []
    for (task_set, task_id), entries in sorted(candidates.items()):
        best = max(entries, key=lambda item: item[0])
        if best[0] < args.min_passes:
            skipped.append(f"{task_set}/{task_id} (best {best[0]} pass(es))")
            continue
        target = ORACLE_DIR / task_set / f"{task_id}.json"
        if target.exists() and not args.overwrite:
            continue
        print(f"{task_set}/{task_id}: {best[0]} pass(es) <- {best[1]}")
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best[1], target)
        written += 1

    print(f"\nWrote {written} oracle trajectories to {ORACLE_DIR}")
    if skipped:
        print(f"Skipped {len(skipped)} tasks below --min-passes={args.min_passes}:")
        for item in skipped:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
