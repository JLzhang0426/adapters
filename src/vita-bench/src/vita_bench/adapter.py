"""
VitaBench -> Harbor adapter.

VitaBench (meituan-longcat/vitabench, ICLR 2026) evaluates LLM agents on
life-service customer tasks (food delivery, in-store consumption, online travel)
in a multi-turn conversation with a simulated user, over a 66-tool environment.
Grading is the official rubric-based sliding-window LLM evaluator.

This adapter converts every task of the four official task sets (delivery,
instore, ota, cross_domain; 100 tasks each) into a Harbor task directory. Each
task packages:

- a Dockerised runtime sidecar (`vita-runtime`) that exposes the original
  environment tools and the simulated user through MCP,
- a verifier that replays the recorded conversation through the official
  `vita.evaluator.evaluate_simulation` routine,
- an oracle solution that replays a pre-validated reference trajectory.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VitaTask:
    task_set: str  # delivery | instore | ota | cross_domain
    env_domain: str  # domain string passed to the vita environment builder
    source_id: str
    local_task_id: str
    task: dict[str, Any]


class VitaBenchAdapter:
    _VITABENCH_REPO_URL = "https://github.com/meituan-longcat/vitabench.git"
    # Pinned upstream commit; keep in sync with task-template/environment/*/Dockerfile.
    _VITABENCH_COMMIT = "742e240855bf8686a0842360749d5ea970ea3987"
    _TEMPLATE_DIR = Path(__file__).parent / "task-template"
    _ORACLE_DIR = Path(__file__).parent / "oracle"
    _DEFAULT_LANGUAGE = "english"

    # Official task sets. `env_domain` is the --domain value used by the original
    # `vita run` CLI for that task set.
    _TASK_SETS: dict[str, dict[str, str]] = {
        "delivery": {"env_domain": "delivery", "slug": "delivery"},
        "instore": {"env_domain": "instore", "slug": "instore"},
        "ota": {"env_domain": "ota", "slug": "ota"},
        "cross_domain": {"env_domain": "delivery,instore,ota", "slug": "cross"},
    }

    def __init__(
        self,
        output_dir: Path,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        **kwargs,
    ):
        self.output_dir = output_dir
        self.limit = limit
        self.overwrite = overwrite
        self.task_ids = task_ids
        self.language = str(kwargs.get("language") or self._DEFAULT_LANGUAGE)
        self.task_sets = self._parse_task_sets(kwargs.get("task_sets"))
        self.vitabench_root = self._resolve_vitabench_root(kwargs.get("vitabench_root"))

    # ------------------------------------------------------------------ setup
    def _parse_task_sets(self, raw: Any) -> list[str]:
        if raw is None:
            return list(self._TASK_SETS)
        if isinstance(raw, str):
            items = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            items = [str(item).strip() for item in raw if str(item).strip()]
        invalid = [item for item in items if item not in self._TASK_SETS]
        if invalid:
            raise ValueError(
                f"Unsupported task set(s): {', '.join(invalid)}. "
                f"Supported: {', '.join(self._TASK_SETS)}"
            )
        return items

    def _is_vitabench_root(self, path: Path) -> bool:
        return (path / "data" / "vita" / "domains").is_dir()

    def _resolve_vitabench_root(self, configured_root: Any) -> Path:
        if configured_root is not None:
            candidate = Path(configured_root).expanduser().resolve()
            if self._is_vitabench_root(candidate):
                return candidate
            return self._clone_vitabench(candidate)

        candidates: list[Path] = []
        env_root = os.getenv("VITABENCH_ROOT")
        if env_root:
            candidates.append(Path(env_root).expanduser())
        cwd = Path.cwd().resolve()
        candidates.extend([cwd.parent / "vitabench", cwd / ".cache" / "vitabench"])
        for candidate in candidates:
            if self._is_vitabench_root(candidate.resolve()):
                return candidate.resolve()

        return self._clone_vitabench(cwd / ".cache" / "vitabench")

    def _clone_vitabench(self, destination: Path) -> Path:
        destination = destination.expanduser().resolve()
        if destination.exists():
            raise FileNotFoundError(
                f"{destination} exists but is not a VitaBench checkout "
                "(expected data/vita/domains)."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", self._VITABENCH_REPO_URL, str(destination)], check=True
        )
        subprocess.run(
            ["git", "-C", str(destination), "checkout", self._VITABENCH_COMMIT],
            check=True,
        )
        if not self._is_vitabench_root(destination):
            raise RuntimeError(f"Clone at {destination} lacks data/vita/domains.")
        return destination

    # ---------------------------------------------------------------- loading
    def _task_file(self, task_set: str) -> Path:
        suffix = "tasks_en.json" if self.language == "english" else "tasks.json"
        return self.vitabench_root / "data" / "vita" / "domains" / task_set / suffix

    def _slugify(self, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
        return normalized or "task"

    def _load_tasks(self) -> list[VitaTask]:
        loaded: list[VitaTask] = []
        for task_set in self.task_sets:
            config = self._TASK_SETS[task_set]
            path = self._task_file(task_set)
            if not path.exists():
                raise FileNotFoundError(f"Missing VitaBench task file: {path}")
            tasks = json.loads(path.read_text(encoding="utf-8"))
            seen: set[str] = set()
            for task in tasks:
                source_id = str(task["id"])
                if source_id in seen:
                    raise ValueError(f"Duplicate task id {source_id} in {task_set}")
                seen.add(source_id)
                loaded.append(
                    VitaTask(
                        task_set=task_set,
                        env_domain=config["env_domain"],
                        source_id=source_id,
                        local_task_id=f"vita-{config['slug']}-{self._slugify(source_id)}",
                        task=task,
                    )
                )
        return loaded

    def _filter_tasks(self, tasks: list[VitaTask]) -> list[VitaTask]:
        if not self.task_ids:
            return tasks
        requested = {task_id.strip() for task_id in self.task_ids if task_id.strip()}
        kept: list[VitaTask] = []
        for task in tasks:
            aliases = {
                task.local_task_id,
                task.source_id,
                f"{task.task_set}:{task.source_id}",
                f"{task.task_set}/{task.source_id}",
            }
            if aliases & requested:
                kept.append(task)
        return kept

    # ---------------------------------------------------------------- writing
    def _read_template(self, relative_path: str) -> str:
        return (self._TEMPLATE_DIR / relative_path).read_text(encoding="utf-8")

    def _copy_template(self, task_dir: Path) -> None:
        ignore = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc")
        for item in self._TEMPLATE_DIR.iterdir():
            if item.name in {".DS_Store", "__pycache__"}:
                continue
            destination = task_dir / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True, ignore=ignore)
            else:
                shutil.copy2(item, destination)

    def _weekday(self, time_str: str) -> str:
        from datetime import datetime

        names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        try:
            return names[datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").weekday()]
        except ValueError:
            return ""

    def _agent_system_prompt(self) -> str:
        """Return the official VitaBench agent system prompt for the language."""
        import yaml

        prompt_path = (
            self.vitabench_root / "src" / "vita" / "prompts" / "agent_system_prompt.yaml"
        )
        prompts = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
        if self.language not in prompts:
            raise ValueError(f"No agent prompt for language {self.language}")
        return str(prompts[self.language])

    def _build_runtime_config(self, vita_task: VitaTask) -> dict[str, Any]:
        return {
            "task_set": vita_task.task_set,
            "env_domain": vita_task.env_domain,
            "language": self.language,
            "source_task_id": vita_task.source_id,
            "harbor_task_id": vita_task.local_task_id,
            "max_steps": 300,
            "max_errors": 10,
            "evaluation_type": "trajectory",
            "task": vita_task.task,
        }

    def _write_instruction(self, task_dir: Path, vita_task: VitaTask) -> None:
        time_str = str(vita_task.task.get("environment", {}).get("time", ""))
        weekday = self._weekday(time_str)
        policy = self._agent_system_prompt().replace(
            "{time}", f"{time_str} {weekday}".strip()
        )
        instruction = self._read_template("instruction.md").replace("{policy}", policy)
        (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")

    def _write_task_toml(self, task_dir: Path, vita_task: VitaTask) -> None:
        content = self._read_template("task.toml")
        content = content.replace("{task_id}", vita_task.local_task_id)
        content = content.replace("{task_set}", vita_task.task_set)
        difficulty = "hard" if vita_task.task_set == "cross_domain" else "medium"
        content = content.replace("{difficulty}", difficulty)
        (task_dir / "task.toml").write_text(content, encoding="utf-8")

    def _write_runtime_assets(self, task_dir: Path, config: dict[str, Any]) -> None:
        runtime_dir = task_dir / "environment" / "runtime-server"
        # The runtime only needs the environment + user scenario, never the rubrics.
        runtime_config = {
            key: value for key, value in config.items() if key != "task"
        }
        runtime_task = {
            key: value
            for key, value in config["task"].items()
            if key != "evaluation_criteria"
        }
        runtime_task["evaluation_criteria"] = None
        runtime_config["task"] = runtime_task
        (runtime_dir / "task_config.json").write_text(
            json.dumps(runtime_config, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _write_test_assets(self, task_dir: Path, config: dict[str, Any]) -> None:
        tests_dir = task_dir / "tests"
        (tests_dir / "config.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # The verifier shares the models.yaml generator with the runtime sidecar.
        shutil.copy2(
            task_dir / "environment" / "runtime-server" / "vita_models_config.py",
            tests_dir / "vita_models_config.py",
        )
        (tests_dir / "test.sh").chmod(0o755)
        (tests_dir / "evaluate.py").chmod(0o755)

    def _write_solution(self, task_dir: Path, vita_task: VitaTask) -> None:
        solution_dir = task_dir / "solution"
        oracle_path = self._ORACLE_DIR / vita_task.task_set / f"{vita_task.source_id}.json"
        if oracle_path.exists():
            shutil.copy2(oracle_path, solution_dir / "oracle_trajectory.json")
        (solution_dir / "solve.sh").chmod(0o755)

    def _write_task(self, vita_task: VitaTask) -> None:
        task_dir = self.output_dir / vita_task.local_task_id
        if task_dir.exists():
            if not self.overwrite:
                return
            shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True)
        self._copy_template(task_dir)

        config = self._build_runtime_config(vita_task)
        self._write_instruction(task_dir, vita_task)
        self._write_task_toml(task_dir, vita_task)
        self._write_runtime_assets(task_dir, config)
        self._write_test_assets(task_dir, config)
        self._write_solution(task_dir, vita_task)

    def run(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tasks = self._filter_tasks(self._load_tasks())
        if self.limit is not None:
            tasks = tasks[: max(0, self.limit)]
        for task in tasks:
            self._write_task(task)
        print(f"Generated {len(tasks)} VitaBench task(s) in {self.output_dir}")
