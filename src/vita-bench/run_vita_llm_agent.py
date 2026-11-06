#!/usr/bin/env python3
"""
In-container runner for the `vita-llm-agent` parity agent.

Drives the *original* VitaBench agent implementation
(`vita.agent.llm_agent.LLMAgent`, including its system prompt handling and its
raw-HTTP `generate` call) against the `vita-runtime` MCP sidecar, replaying the
message routing of `vita.orchestrator.Orchestrator`:

    user/tool message -> LLMAgent.generate_next_message -> runtime
        text         -> submit_assistant_message      -> next user message
        tool calls   -> submit_assistant_tool_calls   -> tool results
        ###STOP###   -> submit_assistant_message      -> agent_stop

Runs inside the task container where the pinned VitaBench package is installed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vita_models_config import write_models_config  # noqa: E402


def _bare_model_name(model: str) -> str:
    """Harbor passes `provider/model`; VitaBench expects the bare model name."""
    return model.split("/", 1)[1] if "/" in model else model


class SchemaTool:
    """Minimal stand-in for `vita.environment.tool.Tool` built from a JSON schema."""

    def __init__(self, schema: dict[str, Any]):
        self._schema = schema
        self.name = schema.get("function", {}).get("name") or schema.get("name")

    @property
    def openai_schema(self) -> dict[str, Any]:
        return self._schema


class McpRuntime:
    def __init__(self, url: str, tool_timeout_sec: float):
        self._url = url
        self._timeout = tool_timeout_sec
        self._client = None
        self._session = None
        self._stack = None

    async def __aenter__(self) -> "McpRuntime":
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._stack = AsyncExitStack()
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(self._url)
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        assert self._session is not None
        result = await asyncio.wait_for(
            self._session.call_tool(name, arguments or {}), timeout=self._timeout
        )
        texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        text = "\n".join(texts)
        if getattr(result, "isError", False):
            raise RuntimeError(f"MCP tool {name} failed: {text}")
        return text


async def run_agent(args: argparse.Namespace) -> dict[str, Any]:
    model = _bare_model_name(args.model)
    write_models_config({model: args.llm_args_json or None})

    from vita.agent.llm_agent import LLMAgent
    from vita.config import models as VITA_MODELS
    from vita.data_model.message import (
        MultiToolMessage,
        ToolMessage,
        UserMessage,
    )

    from vita.environment.environment import get_agent_policy

    instruction = Path(args.instruction_file).read_text(encoding="utf-8")
    env_time = _extract_env_time(instruction)
    # Use the upstream agent system prompt verbatim (LLMAgent fills in {time}).
    policy = get_agent_policy(args.language)

    transcript: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "model": model,
        "seed": args.seed,
        "n_input_tokens": 0,
        "n_output_tokens": 0,
        "cost_usd": 0.0,
        "termination_reason": None,
        "steps": 0,
        "error": None,
    }

    async with McpRuntime(args.mcp_url, args.tool_timeout_sec) as runtime:
        if args.seed is not None or args.max_steps or args.max_errors:
            await runtime.call(
                "configure_run",
                {
                    "seed": args.seed,
                    "max_steps": args.max_steps,
                    "max_errors": args.max_errors,
                },
            )
        schemas = json.loads(await runtime.call("get_assistant_tool_schemas"))
        tools = [SchemaTool(schema) for schema in schemas]

        agent = LLMAgent(
            tools=tools,
            domain_policy=policy,
            llm=model,
            llm_args=dict(VITA_MODELS.get(model, {})),
            time=env_time,
            enable_think=args.enable_think,
            language=args.language,
        )
        if args.seed is not None:
            agent.set_seed(args.seed)
        state = agent.get_init_state()

        first_user_text = await runtime.call("start_conversation")
        message: Any = UserMessage(role="user", content=first_user_text)
        transcript.append({"role": "user", "content": first_user_text})

        steps = 0
        while True:
            # Same invalid-message retry policy as Orchestrator.step().
            agent_msg = None
            for attempt in range(3):
                candidate, new_state = agent.generate_next_message(message, _clone(state))
                if candidate is not None and (
                    candidate.has_text_content() or candidate.is_tool_call()
                ):
                    agent_msg, state = candidate, new_state
                    break
            if agent_msg is None:
                await runtime.call("record_termination", {"reason": "invalid_agent_message"})
                summary["termination_reason"] = "invalid_agent_message"
                break

            _accumulate_usage(summary, agent_msg)
            steps += 1

            if agent_msg.is_tool_call():
                payload = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in agent_msg.tool_calls
                ]
                transcript.append(
                    {"role": "assistant", "content": agent_msg.content, "tool_calls": payload}
                )
                response = json.loads(
                    await runtime.call(
                        "submit_assistant_tool_calls",
                        {"tool_calls_json": json.dumps(payload), "content": agent_msg.content},
                    )
                )
                tool_messages = [
                    ToolMessage(
                        id=r["id"],
                        name=r["name"],
                        role="tool",
                        content=r["content"],
                        requestor="assistant",
                        error=bool(r.get("error")),
                    )
                    for r in response["tool_results"]
                ]
                for tm in tool_messages:
                    transcript.append({"role": "tool", "name": tm.name, "content": tm.content})
                message = (
                    tool_messages[0]
                    if len(tool_messages) == 1
                    else MultiToolMessage(role="tool", tool_messages=tool_messages)
                )
            else:
                transcript.append({"role": "assistant", "content": agent_msg.content})
                response = json.loads(
                    await runtime.call(
                        "submit_assistant_message", {"message": agent_msg.content}
                    )
                )
                observation = response.get("observation")
                if observation is not None:
                    transcript.append({"role": "user", "content": observation})
                    message = UserMessage(role="user", content=observation)

            if response.get("termination_reason"):
                summary["termination_reason"] = response["termination_reason"]
                break
            if args.max_agent_turns and steps >= args.max_agent_turns:
                summary["termination_reason"] = "runner_turn_limit"
                break

        summary["steps"] = steps

    return {"summary": summary, "transcript": transcript}


def _clone(state: Any) -> Any:
    from copy import deepcopy

    return deepcopy(state)


def _extract_env_time(instruction: str) -> str:
    """Read the task's environment time from the rendered instruction.md."""
    import re

    match = re.search(
        r"Current time:\s*([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})",
        instruction,
    )
    if not match:
        raise ValueError("Could not find 'Current time:' in the instruction.")
    return match.group(1)


def _accumulate_usage(summary: dict[str, Any], message: Any) -> None:
    usage = getattr(message, "usage", None) or {}
    summary["n_input_tokens"] += int(usage.get("prompt_tokens") or 0)
    summary["n_output_tokens"] += int(usage.get("completion_tokens") or 0)
    cost = getattr(message, "cost", None)
    if cost:
        summary["cost_usd"] += float(cost)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--instruction-file", required=True)
    parser.add_argument("--mcp-url", required=True)
    parser.add_argument("--language", default="english")
    parser.add_argument("--seed", type=lambda s: None if s == "none" else int(s), default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--max-errors", type=int, default=None)
    parser.add_argument("--max-agent-turns", type=int, default=0)
    parser.add_argument("--enable-think", action="store_true")
    parser.add_argument("--llm-args-json", default=None)
    parser.add_argument("--tool-timeout-sec", type=float, default=600.0)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--transcript-path", required=True)
    args = parser.parse_args()

    started = time.time()
    try:
        output = asyncio.run(run_agent(args))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        output = {
            "summary": {"error": f"{type(exc).__name__}: {exc}", "model": args.model},
            "transcript": [],
        }
    output["summary"]["duration_sec"] = time.time() - started
    output["summary"]["metadata"] = {
        "agent": "vita-llm-agent",
        "seed": args.seed,
        "language": args.language,
        "enable_think": args.enable_think,
    }

    for path, payload in (
        (args.summary_path, output["summary"]),
        (args.transcript_path, output["transcript"]),
    ):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
    print(json.dumps(output["summary"], default=str))
    if output["summary"].get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
