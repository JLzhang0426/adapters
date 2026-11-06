"""
`vita-llm-agent`: parity agent for the VitaBench Harbor adapter.

A Harbor installed agent that uploads `run_vita_llm_agent.py` into the task
container and runs it there. The runner drives the original VitaBench
`LLMAgent` (same system prompt, same tool schemas, same raw-HTTP `generate`)
against the `vita-runtime` MCP sidecar, so Harbor runs match the upstream
`vita run --agent-llm <model>` loop as closely as possible.

Usage (from the adapters repo root):

    PYTHONPATH="$PWD/src/vita-bench" uv run --project src/vita-bench harbor run \
        -p datasets/vita-bench --agent-import-path vita_llm_agent:VitaLLMAgent \
        -m "openai/gpt-4.1"
"""

from __future__ import annotations

import json
import os
import random
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import MCPServerConfig

RUNNER_FILENAME = "run_vita_llm_agent.py"
MODELS_CONFIG_FILENAME = "vita_models_config.py"
MODELS_CONFIG_SOURCE = (
    Path(__file__).parent
    / "src"
    / "vita_bench"
    / "task-template"
    / "environment"
    / "runtime-server"
    / MODELS_CONFIG_FILENAME
)
RUNNER_TARGET_DIR = "/opt/vita-llm-agent"
INSTRUCTION_TARGET_PATH = "/tmp/vita_llm_agent_instruction.md"
SUMMARY_FILENAME = "vita-llm-agent-summary.json"
TRANSCRIPT_FILENAME = "vita-llm-agent-transcript.json"
DEFAULT_VERSION = "1.0"
DEFAULT_MAX_STEPS = 300  # vita.config.DEFAULT_MAX_STEPS
DEFAULT_MAX_ERRORS = 10  # vita.config.DEFAULT_MAX_ERRORS
DEFAULT_SEED = 300  # vita.config.DEFAULT_SEED


class VitaLLMAgent(BaseInstalledAgent):
    capabilities = AgentCapabilities(mcp_servers=True, base_url=True)

    def __init__(
        self,
        *args: Any,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_errors: int = DEFAULT_MAX_ERRORS,
        seed: int | None = DEFAULT_SEED,
        derive_trial_seed: bool = True,
        vita_trial_index: int = 0,
        enable_think: bool = False,
        language: str = "english",
        llm_args_json: str | None = None,
        tool_timeout_sec: float = 600.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._max_steps = max_steps
        self._max_errors = max_errors
        self._seed = seed
        self._derive_trial_seed = derive_trial_seed
        self._vita_trial_index = vita_trial_index
        self._enable_think = enable_think
        self._language = language
        self._llm_args_json = llm_args_json
        self._tool_timeout_sec = tool_timeout_sec

    @staticmethod
    def name() -> str:
        return "vita-llm-agent"

    def version(self) -> str | None:
        return self._version or DEFAULT_VERSION

    async def install(self, environment: BaseEnvironment) -> None:
        # The task image already ships VitaBench; only the MCP client is extra.
        await self.exec_as_root(
            environment, command="python3 -m pip install --no-cache-dir 'mcp>=1.25,<2'"
        )
        await self.exec_as_root(environment, command=f"mkdir -p {RUNNER_TARGET_DIR}")
        for source, filename in (
            (Path(__file__).with_name(RUNNER_FILENAME), RUNNER_FILENAME),
            (MODELS_CONFIG_SOURCE, MODELS_CONFIG_FILENAME),
        ):
            local_copy = self.logs_dir / filename
            local_copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            await environment.upload_file(local_copy, f"{RUNNER_TARGET_DIR}/{filename}")

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        if not self.model_name:
            raise ValueError("model_name is required for VitaLLMAgent")
        runtime_server = self._resolve_runtime_server()

        instruction_copy = self.logs_dir / "vita-llm-agent.instruction.md"
        instruction_copy.write_text(instruction, encoding="utf-8")
        await environment.upload_file(instruction_copy, INSTRUCTION_TARGET_PATH)

        await self.exec_as_agent(
            environment,
            command=self._build_run_command(runtime_server.url or ""),
            env=self._build_runner_env(),
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        summary_path = self.logs_dir / SUMMARY_FILENAME
        if not summary_path.exists():
            return
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        context.n_input_tokens = _as_int(summary.get("n_input_tokens"))
        context.n_output_tokens = _as_int(summary.get("n_output_tokens"))
        context.cost_usd = _as_float(summary.get("cost_usd"))
        metadata = summary.get("metadata")
        if isinstance(metadata, dict):
            metadata = dict(metadata)
            metadata["termination_reason"] = summary.get("termination_reason")
            metadata["vita_trial_index"] = self._vita_trial_index
            context.metadata = metadata

    def _resolve_runtime_server(self) -> MCPServerConfig:
        servers = [s for s in self.mcp_servers if s.name == "vita-runtime"] or list(
            self.mcp_servers
        )
        if len(servers) != 1:
            raise ValueError(
                f"VitaLLMAgent expects exactly one MCP server, got {len(servers)}"
            )
        server = servers[0]
        if server.transport != "streamable-http" or not server.url:
            raise ValueError("VitaLLMAgent requires a streamable-http MCP server URL")
        return server

    def _build_runner_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
            value = self._get_env(key)
            if value:
                env[key] = value
        if "OPENAI_BASE_URL" not in env and env.get("OPENAI_API_BASE"):
            env["OPENAI_BASE_URL"] = env["OPENAI_API_BASE"]
        env["VITA_MODEL_CONFIG_PATH"] = f"{RUNNER_TARGET_DIR}/models.yaml"
        return env

    def _build_run_command(self, mcp_url: str) -> str:
        seed = self._effective_seed()
        parts = [
            "python3",
            f"{RUNNER_TARGET_DIR}/{RUNNER_FILENAME}",
            "--model",
            shlex.quote(self.model_name or ""),
            "--instruction-file",
            shlex.quote(INSTRUCTION_TARGET_PATH),
            "--mcp-url",
            shlex.quote(mcp_url),
            "--language",
            shlex.quote(self._language),
            "--max-steps",
            str(self._max_steps),
            "--max-errors",
            str(self._max_errors),
            "--seed",
            "none" if seed is None else str(seed),
            "--tool-timeout-sec",
            str(self._tool_timeout_sec),
            "--summary-path",
            shlex.quote(f"/logs/agent/{SUMMARY_FILENAME}"),
            "--transcript-path",
            shlex.quote(f"/logs/agent/{TRANSCRIPT_FILENAME}"),
        ]
        if self._enable_think:
            parts.append("--enable-think")
        if self._llm_args_json:
            parts.extend(["--llm-args-json", shlex.quote(self._llm_args_json)])
        command = " ".join(parts)
        return f"{command} 2>&1 | tee /logs/agent/vita-llm-agent.txt"

    def _effective_seed(self) -> int | None:
        """Mirror vita.run.run_tasks: random.seed(seed); one randint per trial."""
        if self._seed is None or not self._derive_trial_seed:
            return self._seed
        rng = random.Random(self._seed)
        seeds = [rng.randint(0, 1_000_000) for _ in range(self._vita_trial_index + 1)]
        return seeds[self._vita_trial_index]


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
