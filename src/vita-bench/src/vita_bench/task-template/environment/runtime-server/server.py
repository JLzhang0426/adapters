"""
VitaBench runtime sidecar.

Exposes one VitaBench task (environment tools + database + simulated user)
through an MCP streamable-http server, mirroring the original
`vita.orchestrator.Orchestrator` loop:

    agent -> (tool call) -> environment -> agent
    agent -> (message)   -> user        -> agent

The full conversation is persisted to /logs/agent/vita_runtime_state.json after
every step so the verifier can replay it through the official evaluator.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vita_models_config import write_models_config  # noqa: E402

USER_MODEL = os.environ.get("VITA_USER_MODEL", "gpt-4.1")
write_models_config({USER_MODEL: os.environ.get("VITA_USER_LLM_ARGS_JSON") or None})

from fastmcp import FastMCP  # noqa: E402
from vita.config import models as VITA_MODELS  # noqa: E402
from vita.data_model.message import (  # noqa: E402
    AssistantMessage,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from vita.data_model.simulation import TerminationReason  # noqa: E402
from vita.data_model.tasks import Task  # noqa: E402
from vita.environment.environment import get_cross_environment  # noqa: E402
from vita.orchestrator.orchestrator import (  # noqa: E402
    get_default_first_agent_message,
)
from vita.registry import registry  # noqa: E402
from vita.user.user_simulator import UserSimulator  # noqa: E402
from vita.utils.utils import format_time, get_now  # noqa: E402

TASK_CONFIG_PATH = Path("/app/task_config.json")
STATE_LOG_PATH = Path(
    os.environ.get("VITA_RUNTIME_STATE_PATH", "/logs/agent/vita_runtime_state.json")
)
STOP_TOKEN = "###STOP###"

mcp = FastMCP("vita-runtime")


def make_domain_tool_handler(
    tool: Any, call_assistant_tool: Callable[[str, dict[str, Any]], str]
) -> Callable[..., str]:
    tool_name = tool.name
    raw_signature = getattr(tool, "__signature__", None) or inspect.signature(tool)
    signature = raw_signature.replace(return_annotation=str)

    annotations: dict[str, Any] = {"return": str}
    for param_name, param in signature.parameters.items():
        annotation = param.annotation
        if annotation is inspect.Signature.empty:
            annotation = Any
        annotations[param_name] = annotation

    def _tool_handler(**kwargs: Any) -> str:
        return call_assistant_tool(tool_name, kwargs)

    _tool_handler.__name__ = tool_name
    _tool_handler.__qualname__ = tool_name
    _tool_handler.__doc__ = getattr(tool, "__doc__", None) or f"Call {tool_name}."
    _tool_handler.__signature__ = signature
    _tool_handler.__annotations__ = annotations
    return _tool_handler


class VitaRuntime:
    def __init__(self, config_path: Path):
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.env_domain = str(self.config["env_domain"])
        self.language = str(self.config.get("language") or "english")
        self.task = Task.model_validate(self.config["task"])
        self.max_steps = int(self.config.get("max_steps") or 300)
        self.max_errors = int(self.config.get("max_errors") or 10)

        if self.task.message_history:
            raise NotImplementedError(
                "VitaBench tasks with a pre-existing message history are not supported."
            )

        if "," in self.env_domain:
            self.environment = get_cross_environment(
                self.env_domain, self.task.environment, self.language
            )
        else:
            constructor = registry.get_env_constructor(self.env_domain)
            self.environment = constructor(self.task.environment, self.language)

        self.user_llm_args: dict[str, Any] = deepcopy(VITA_MODELS.get(USER_MODEL, {}))
        self.user = UserSimulator(
            persona=str(self.task.user_scenario.user_profile),
            instructions=str(self.task.instructions),
            llm=USER_MODEL,
            llm_args=self.user_llm_args,
            language=self.language,
        )
        self.user_state = self.user.get_init_state()

        self.messages: list[Any] = []
        self.termination_reason: str | None = None
        self.step_count = 0
        self.num_errors = 0
        self.seed: int | None = None
        self.start_tool_called = False
        self.last_agent_observation = ""
        self._tool_call_counter = 0
        self._oracle_replay = False
        self._oracle_messages: list[dict[str, Any]] | None = None
        self._oracle_states: dict[str, Any] | None = None
        self._write_state()

    # ------------------------------------------------------------- helpers
    def _next_tool_call_id(self) -> str:
        self._tool_call_counter += 1
        return f"runtime_tool_{self._tool_call_counter}"

    def _stamp(self, message: Any) -> Any:
        message.timestamp = get_now("%Y%m%d_%H%M%S_%f")
        return message

    def state_payload(self) -> dict[str, Any]:
        return {
            "task_set": self.config.get("task_set"),
            "env_domain": self.env_domain,
            "language": self.language,
            "task_id": self.task.id,
            "user_model": USER_MODEL,
            "termination_reason": self.termination_reason,
            "step_count": self.step_count,
            "num_errors": self.num_errors,
            "max_steps": self.max_steps,
            "max_errors": self.max_errors,
            "seed": self.seed,
            "start_tool_called": self.start_tool_called,
            "messages": (
                self._oracle_messages
                if self._oracle_messages is not None
                else [message.model_dump(mode="json") for message in self.messages]
            ),
            "states": (
                self._oracle_states
                if self._oracle_states is not None
                else self._dump_states()
            ),
            "oracle_replay": self._oracle_replay,
        }

    def _write_state(self) -> None:
        STATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_LOG_PATH.write_text(
            json.dumps(self.state_payload(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def load_oracle_state(self, oracle: dict[str, Any]) -> dict[str, Any]:
        """Replace the live conversation with a stored (oracle) trajectory."""
        if self.start_tool_called and self._oracle_replay is False and self.messages:
            raise RuntimeError("Cannot load an oracle trajectory into a started run.")
        messages = oracle.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("Oracle trajectory must contain a non-empty messages list.")
        self._oracle_messages = messages
        self.termination_reason = oracle.get("termination_reason")
        self._oracle_states = oracle.get("states") or {"old_states": [], "new_states": []}
        self.step_count = int(oracle.get("step_count") or 0)
        self.num_errors = int(oracle.get("num_errors") or 0)
        self.seed = oracle.get("seed")
        self.start_tool_called = True
        self._oracle_replay = True
        self._write_state()
        return self.state_payload()

    def _dump_states(self) -> dict[str, Any]:
        """Same split as Orchestrator.get_states (old vs. new DB records)."""
        from vita.utils.utils import str_to_datetime

        db = getattr(self.environment.tools, "db", None)
        if db is None:
            return {"old_states": [], "new_states": []}
        records: list[Any] = []
        for attr in ("orders", "books", "reservations"):
            if hasattr(db, attr):
                records += list(getattr(db, attr).values())
        env_time = str_to_datetime(db.time)
        out: dict[str, list[Any]] = {"old_states": [], "new_states": []}
        for record in records:
            bucket = (
                "old_states"
                if str_to_datetime(record.update_time) < env_time
                else "new_states"
            )
            out[bucket].append(
                record.model_dump(mode="json")
                if hasattr(record, "model_dump")
                else record
            )
        return out

    def _require_active(self) -> None:
        if self.termination_reason is not None:
            raise RuntimeError(
                f"Conversation has already ended with reason '{self.termination_reason}'."
            )

    def _require_started(self) -> None:
        if not self.start_tool_called:
            raise RuntimeError("Call start_conversation first.")

    def _check_termination(self) -> None:
        if self.termination_reason is not None:
            return
        if self.step_count >= self.max_steps:
            self.termination_reason = TerminationReason.MAX_STEPS.value
        elif self.num_errors >= self.max_errors:
            self.termination_reason = TerminationReason.TOO_MANY_ERRORS.value

    def _finish_step(self) -> None:
        self.step_count += 1
        self._check_termination()
        self._write_state()

    def _format_observation(self, message: Any) -> str:
        if isinstance(message, MultiToolMessage):
            return "\n\n".join(m.content or "" for m in message.tool_messages)
        content = getattr(message, "content", None)
        return "" if content is None else str(content)

    def _status(self, observation: str | None) -> str:
        return json.dumps(
            {
                "observation": observation,
                "termination_reason": self.termination_reason,
                "step_count": self.step_count,
                "num_errors": self.num_errors,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    # ---------------------------------------------------------- core loop
    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolMessage]:
        results = []
        for tool_call in tool_calls:
            result = self.environment.get_response(tool_call)
            if result.error:
                self.num_errors += 1
            results.append(self._stamp(result))
        self.messages.extend(results)
        self._finish_step()
        return results

    def _run_user_turn(self, incoming: Any) -> Any:
        """Advance the simulated user until the agent gets an observation."""
        current = incoming
        while True:
            self._require_active()
            user_message, self.user_state = self.user.generate_next_message(
                current, self.user_state
            )
            user_message.validate()
            self.messages.append(self._stamp(user_message))
            if UserSimulator.is_stop(user_message):
                self.termination_reason = TerminationReason.USER_STOP.value
                self._finish_step()
                return user_message
            if user_message.is_tool_call():
                self._finish_step()
                if self.termination_reason is not None:
                    return user_message
                results = self._execute_tool_calls(user_message.tool_calls)
                current = (
                    results[0]
                    if len(results) == 1
                    else MultiToolMessage(role="tool", tool_messages=results)
                )
                if self.termination_reason is not None:
                    return current
                continue
            self._finish_step()
            return user_message

    # ------------------------------------------------------------ MCP API
    def configure_run(
        self, seed: int | None = None, max_steps: int | None = None,
        max_errors: int | None = None,
    ) -> str:
        if self.start_tool_called:
            raise RuntimeError("Run must be configured before start_conversation.")
        if max_steps is not None:
            self.max_steps = max_steps
        if max_errors is not None:
            self.max_errors = max_errors
        if seed is not None:
            self.seed = seed
            self.user.set_seed(seed)
        self._write_state()
        return self.get_runtime_status()

    def get_runtime_status(self) -> str:
        return json.dumps(
            {
                "termination_reason": self.termination_reason,
                "step_count": self.step_count,
                "num_errors": self.num_errors,
                "max_steps": self.max_steps,
                "max_errors": self.max_errors,
                "seed": self.seed,
                "started": self.start_tool_called,
            },
            sort_keys=True,
        )

    def get_assistant_tool_schemas(self) -> str:
        return json.dumps(
            [tool.openai_schema for tool in self.environment.get_tools()],
            ensure_ascii=False,
        )

    def start_conversation(self) -> str:
        if self.start_tool_called:
            return self.last_agent_observation
        self.start_tool_called = True
        first = deepcopy(get_default_first_agent_message(self.language))
        self.messages.append(self._stamp(first))
        self._write_state()
        observation = self._run_user_turn(first)
        self.last_agent_observation = self._format_observation(observation)
        self._write_state()
        return self.last_agent_observation

    def submit_assistant_message(self, message: str) -> str:
        if not message.strip():
            raise ValueError("Message must not be empty.")
        self._require_started()
        self._require_active()
        assistant_message = AssistantMessage(role="assistant", content=message)
        assistant_message.validate()
        self.messages.append(self._stamp(assistant_message))
        if STOP_TOKEN in message:
            self.termination_reason = TerminationReason.AGENT_STOP.value
            self._finish_step()
            return self._status(None)
        self._finish_step()
        if self.termination_reason is not None:
            return self._status(None)
        observation = self._run_user_turn(assistant_message)
        self.last_agent_observation = self._format_observation(observation)
        self._write_state()
        return self._status(self.last_agent_observation)

    def send_message_to_user(self, message: str) -> str:
        response = json.loads(self.submit_assistant_message(message))
        observation = response.get("observation")
        if observation is None:
            return (
                "Conversation ended "
                f"(termination_reason={response.get('termination_reason')})."
            )
        return str(observation)

    def submit_assistant_tool_calls(
        self, tool_calls_json: str, content: str | None = None
    ) -> str:
        self._require_started()
        self._require_active()
        raw_calls = json.loads(tool_calls_json)
        if not isinstance(raw_calls, list) or not raw_calls:
            raise ValueError("tool_calls_json must decode to a non-empty list.")
        tool_calls = [
            ToolCall(
                id=str(raw.get("id") or self._next_tool_call_id()),
                name=str(raw["name"]),
                arguments=dict(raw.get("arguments") or {}),
                requestor="assistant",
            )
            for raw in raw_calls
        ]
        assistant_message = AssistantMessage(
            role="assistant", content=content, tool_calls=tool_calls
        )
        assistant_message.validate()
        self.messages.append(self._stamp(assistant_message))
        self._finish_step()
        self._require_active()
        results = self._execute_tool_calls(tool_calls)
        observation = "\n\n".join(r.content or "" for r in results)
        self.last_agent_observation = observation
        self._write_state()
        return json.dumps(
            {
                "tool_results": [
                    {"id": r.id, "name": r.name, "content": r.content or "", "error": r.error}
                    for r in results
                ],
                "observation": observation,
                "termination_reason": self.termination_reason,
                "step_count": self.step_count,
                "num_errors": self.num_errors,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def call_assistant_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        self._require_started()
        self._require_active()
        tool_call = ToolCall(
            id=self._next_tool_call_id(),
            name=tool_name,
            arguments=arguments,
            requestor="assistant",
        )
        assistant_message = AssistantMessage(
            role="assistant", content=None, tool_calls=[tool_call]
        )
        assistant_message.validate()
        self.messages.append(self._stamp(assistant_message))
        self._finish_step()
        self._require_active()
        results = self._execute_tool_calls([tool_call])
        self.last_agent_observation = results[0].content or ""
        self._write_state()
        return self.last_agent_observation

    def end_conversation(self, message: str = STOP_TOKEN) -> str:
        if self.termination_reason is not None:
            return f"Conversation already ended with reason '{self.termination_reason}'."
        self._require_started()
        if STOP_TOKEN not in message:
            message = f"{message} {STOP_TOKEN}".strip()
        stop_message = AssistantMessage(role="assistant", content=message)
        stop_message.validate()
        self.messages.append(self._stamp(stop_message))
        self.termination_reason = TerminationReason.AGENT_STOP.value
        self._finish_step()
        return "Conversation ended."

    def record_termination(self, reason: str) -> str:
        if reason not in {item.value for item in TerminationReason}:
            raise ValueError(f"Unsupported termination reason: {reason}")
        self.termination_reason = reason
        self._write_state()
        return self.get_runtime_status()


runtime = VitaRuntime(TASK_CONFIG_PATH)


@mcp.tool()
def configure_run(
    seed: int | None = None, max_steps: int | None = None, max_errors: int | None = None
) -> str:
    """Configure run parameters (seed, step/error limits) before start_conversation."""
    return runtime.configure_run(seed=seed, max_steps=max_steps, max_errors=max_errors)


@mcp.tool()
def get_runtime_status() -> str:
    """Return step count, error count, limits, seed and termination status."""
    return runtime.get_runtime_status()


@mcp.tool()
def get_assistant_tool_schemas() -> str:
    """Return the original VitaBench OpenAI-style JSON schemas of the platform tools."""
    return runtime.get_assistant_tool_schemas()


@mcp.tool()
def start_conversation() -> str:
    """Start the conversation and return the user's first message."""
    return runtime.start_conversation()


@mcp.tool()
def submit_assistant_message(message: str) -> str:
    """Record an assistant message, advance the user simulator, return JSON status."""
    return runtime.submit_assistant_message(message)


@mcp.tool()
def submit_assistant_tool_calls(tool_calls_json: str, content: str | None = None) -> str:
    """Record one assistant tool-call message (JSON list of {id,name,arguments}) and execute it."""
    return runtime.submit_assistant_tool_calls(tool_calls_json, content)


@mcp.tool()
def send_message_to_user(message: str) -> str:
    """Send a message to the user and return the user's reply."""
    return runtime.send_message_to_user(message)


@mcp.tool()
def end_conversation(message: str = STOP_TOKEN) -> str:
    """End the conversation once the user has confirmed there is nothing else."""
    return runtime.end_conversation(message)


@mcp.tool()
def record_termination(reason: str) -> str:
    """Record a non-success termination reason (max_steps, too_many_errors, ...)."""
    return runtime.record_termination(reason)


@mcp.custom_route("/state", methods=["GET"])
async def http_get_state(request: Any) -> Any:
    """Export the recorded conversation (used by the verifier)."""
    from starlette.responses import JSONResponse

    return JSONResponse(json.loads(json.dumps(runtime.state_payload(), default=str)))


@mcp.custom_route("/state", methods=["POST"])
async def http_post_state(request: Any) -> Any:
    """Load a stored oracle trajectory (used by the oracle solution)."""
    from starlette.responses import JSONResponse

    try:
        oracle = await request.json()
        payload = runtime.load_oracle_state(oracle)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)
    return JSONResponse(
        {"ok": True, "num_messages": len(payload["messages"]),
         "termination_reason": payload["termination_reason"]}
    )


@mcp.custom_route("/health", methods=["GET"])
async def http_health(request: Any) -> Any:
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "started": runtime.start_tool_called})


def _register_domain_tools() -> None:
    for tool in runtime.environment.get_tools():
        mcp.tool()(make_domain_tool_handler(tool, runtime.call_assistant_tool))


_register_domain_tools()


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
