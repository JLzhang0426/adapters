#!/usr/bin/env python3
"""
VitaBench verifier.

Reads the conversation recorded by the `vita-runtime` sidecar
(/logs/agent/vita_runtime_state.json), rebuilds the official
`vita.data_model.simulation.SimulationRun`, and scores it with the official
`vita.evaluator.evaluate_simulation` (rubric-based sliding-window LLM
evaluator). The binary reward (1.0 only if every rubric is met) is written to
the Harbor reward file; the per-rubric breakdown goes to result.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vita_models_config import write_models_config  # noqa: E402

EVALUATOR_MODEL = os.environ.get("VITA_EVALUATOR_MODEL", "claude-sonnet-4-5")
write_models_config(
    {EVALUATOR_MODEL: os.environ.get("VITA_EVALUATOR_LLM_ARGS_JSON") or None}
)

from vita.config import models as VITA_MODELS  # noqa: E402
from vita.data_model.message import (  # noqa: E402
    AssistantMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from vita.data_model.simulation import SimulationRun  # noqa: E402
from vita.data_model.tasks import Task  # noqa: E402
from vita.evaluator.evaluator import evaluate_simulation  # noqa: E402


def _parse_message(raw: dict[str, Any]) -> Any:
    role = raw.get("role")
    if role == "tool":
        return ToolMessage.model_validate(raw)
    tool_calls = raw.get("tool_calls")
    if tool_calls:
        raw = dict(raw)
        raw["tool_calls"] = [ToolCall.model_validate(tc) for tc in tool_calls]
    if role == "assistant":
        return AssistantMessage.model_validate(raw)
    if role == "user":
        return UserMessage.model_validate(raw)
    raise ValueError(f"Unsupported message role: {role!r}")


def _result(status: str, reward: float, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "reward": reward}
    payload.update(extra)
    return payload


def _evaluate(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    task = Task.model_validate(config["task"])
    language = str(config.get("language") or "english")
    env_domain = str(config["env_domain"])
    evaluation_type = str(config.get("evaluation_type") or "trajectory")

    raw_messages = state.get("messages") or []
    messages = [_parse_message(raw) for raw in raw_messages]
    for idx, message in enumerate(messages):
        message.turn_idx = idx

    termination_reason = state.get("termination_reason")
    if termination_reason is None:
        # The agent never closed the conversation. Treat it like the original
        # harness does when the step budget runs out: no reward.
        return _result(
            "conversation_not_terminated",
            0.0,
            note="The conversation was never terminated (no ###STOP### from the "
            "agent and no user stop). VitaBench grants no reward in this case.",
            num_messages=len(messages),
        )

    simulation = SimulationRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        start_time="",
        end_time="",
        duration=0.0,
        termination_reason=termination_reason,
        messages=messages,
        states=state.get("states") or {"old_states": [], "new_states": []},
        seed=state.get("seed"),
    )

    reward_info = evaluate_simulation(
        simulation=simulation,
        task=task,
        evaluation_type=evaluation_type,
        domain=env_domain,
        llm_evaluator=EVALUATOR_MODEL,
        llm_args_evaluator=dict(VITA_MODELS.get(EVALUATOR_MODEL, {})),
        language=language,
    )
    rubrics = [
        {"rubric": check.nl_rubric, "met": check.met, "justification": check.justification}
        for check in (reward_info.nl_rubrics or [])
    ]
    return _result(
        "evaluated",
        float(reward_info.reward),
        termination_reason=termination_reason,
        evaluator_model=EVALUATOR_MODEL,
        evaluation_type=evaluation_type,
        num_messages=len(messages),
        num_rubrics=len(rubrics),
        num_rubrics_met=sum(1 for r in rubrics if r["met"]),
        reward_breakdown={
            str(k): v for k, v in (reward_info.reward_breakdown or {}).items()
        },
        rubrics=rubrics,
        info=reward_info.info,
    )


def _load_state(runtime_url: str, runtime_log: Path) -> tuple[dict[str, Any] | None, str]:
    """Fetch the conversation from the sidecar; fall back to the local log file."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{runtime_url}/state", timeout=60) as response:
            state = json.loads(response.read().decode("utf-8"))
            if state.get("messages") or not runtime_log.exists():
                return state, f"{runtime_url}/state"
    except Exception as exc:  # noqa: BLE001
        print(f"Could not fetch state from {runtime_url}: {exc}", file=sys.stderr)
    if runtime_log.exists():
        return json.loads(runtime_log.read_text(encoding="utf-8")), str(runtime_log)
    return None, ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime-log", type=Path, required=True)
    parser.add_argument(
        "--runtime-url",
        default=os.environ.get("VITA_RUNTIME_URL", "http://vita-runtime:8000"),
    )
    parser.add_argument("--reward", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))

    try:
        state, source = _load_state(args.runtime_url, args.runtime_log)
        if state is None:
            result = _result(
                "missing_runtime_log",
                0.0,
                note="No conversation state: sidecar unreachable and "
                f"{args.runtime_log} missing.",
            )
        else:
            # Keep a copy with the verifier outputs (Harbor collects this dir).
            saved = args.result.parent / "vita_runtime_state.json"
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(
                json.dumps(state, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            result = _evaluate(config, state)
            result["state_source"] = source
    except Exception as exc:  # noqa: BLE001
        # Infrastructure failure (e.g. evaluator LLM unreachable; upstream
        # `generate` swallows HTTP errors and returns None). Do not write a
        # reward so Harbor records an errored trial instead of a false 0.
        traceback.print_exc()
        result = _result("evaluator_error", 0.0, note=f"{type(exc).__name__}: {exc}")
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(json.dumps(result, default=str))
        sys.exit(1)

    args.reward.parent.mkdir(parents=True, exist_ok=True)
    args.reward.write_text(str(result["reward"]), encoding="utf-8")
    args.result.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "rubrics"}, default=str))
    for rubric in result.get("rubrics", []):
        flag = "MET  " if rubric["met"] else "UNMET"
        print(f"[{flag}] {rubric['rubric']}\n        -> {rubric['justification']}")


if __name__ == "__main__":
    main()
