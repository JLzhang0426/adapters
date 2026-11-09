"""
LongBench v2 -> Harbor adapter.

LongBench v2 (THUDM/LongBench, arXiv:2412.15204) is a set of 503 human-written,
expert-reviewed multiple-choice questions over long contexts (8k-2M words) in six
categories: single-document QA, multi-document QA, long in-context learning,
long-dialogue history understanding, code repository understanding, and long
structured data understanding. Each question has four choices and one gold
letter (A-D).

The adapter converts every question into a Harbor task:

- the long context is shipped as /app/context.txt inside the task image,
- instruction.md reproduces the official zero-shot prompt (prompts/0shot.txt),
  pointing the agent at the context file and asking for the answer in
  /app/answer.txt,
- the verifier extracts the letter with the official regex logic and awards
  1.0 on an exact match,
- the oracle writes the gold letter.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------- provenance
# Dataset: Hugging Face `zai-org/LongBench-v2` (formerly `THUDM/LongBench-v2`;
# the old name redirects). Pinned to an immutable commit so that content and
# order -- and therefore task ids and the stratified parity split -- cannot
# drift under us.
DATA_REPO = "zai-org/LongBench-v2"
DATA_REVISION = "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9"  # 2024-12-20
DATA_FILE = "data.json"
DATA_URL = f"https://huggingface.co/datasets/{DATA_REPO}/resolve/{DATA_REVISION}/{DATA_FILE}"
# sha256 of data.json at DATA_REVISION (Git LFS object id), 465,490,535 bytes.
DATA_SHA256 = "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2"
DATA_SIZE_BYTES = 465_490_535

# Prompt + scorer: GitHub `THUDM/LongBench` (prompts/0shot.txt, pred.py
# extract_answer, result.py). Pinned to the repository HEAD at adaptation time;
# the three files were last changed in c5ea10b (0shot.txt, pred.py) and
# 5214a55 (result.py).
UPSTREAM_CODE_REPO = "THUDM/LongBench"
UPSTREAM_CODE_REVISION = "2e00731f8d0bff23dc4325161044d0ed8af94c1e"  # 2025-01-15

@dataclass(frozen=True)
class LongBenchItem:
    index: int
    source_id: str
    local_task_id: str
    record: dict[str, Any]


class LongBenchV2Adapter:
    _TEMPLATE_DIR = Path(__file__).parent / "task-template"
    _DOMAINS = {
        "Single-Document QA": "single-doc-qa",
        "Multi-Document QA": "multi-doc-qa",
        "Long In-context Learning": "long-icl",
        "Long-dialogue History Understanding": "long-dialogue",
        "Code Repository Understanding": "code-repo",
        "Long Structured Data Understanding": "structured-data",
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
        self.split = str(kwargs.get("split") or "full")
        self.skip_checksum = bool(kwargs.get("skip_checksum", False))
        self.data_path = self._resolve_data_path(kwargs.get("data_path"))
        self._verify_checksum(self.data_path)

    # ------------------------------------------------------------------ data
    def _resolve_data_path(self, configured: Any) -> Path:
        candidates: list[Path] = []
        if configured:
            candidates.append(Path(configured).expanduser())
        env = os.getenv("LONGBENCH_V2_DATA")
        if env:
            candidates.append(Path(env).expanduser())
        cache = Path.cwd() / ".cache" / "longbench-v2" / "data.json"
        candidates.append(cache)
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"Downloading LongBench v2 {DATA_FILE} (~465 MB) at revision "
            f"{DATA_REVISION[:12]} to {cache} ..."
        )
        tmp = cache.with_suffix(".part")
        urllib.request.urlretrieve(DATA_URL, tmp)
        tmp.rename(cache)
        return cache.resolve()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_checksum(self, path: Path) -> None:
        """Refuse to generate tasks from anything but the pinned data.json."""
        if self.skip_checksum:
            print(f"WARNING: --skip-checksum set; not verifying {path} against {DATA_SHA256[:12]}...")
            return
        actual = self._sha256(path)
        if actual != DATA_SHA256:
            raise ValueError(
                f"{path} does not match the pinned LongBench v2 dataset "
                f"({DATA_REPO}@{DATA_REVISION[:12]}):\n"
                f"  expected sha256 {DATA_SHA256}\n"
                f"  actual   sha256 {actual}\n"
                "Delete the file to re-download the pinned revision, or pass "
                "--skip-checksum to generate tasks from a different file (they will "
                "not be comparable to the registered benchmark)."
            )

    def _load_items(self) -> list[LongBenchItem]:
        records = json.loads(self.data_path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("LongBench v2 data.json must be a list of records")
        items: list[LongBenchItem] = []
        seen: set[str] = set()
        for index, record in enumerate(records):
            source_id = str(record["_id"])
            if source_id in seen:
                raise ValueError(f"Duplicate _id in dataset: {source_id}")
            seen.add(source_id)
            if record["domain"] not in self._DOMAINS:
                raise ValueError(f"Unknown domain: {record['domain']!r}")
            if record["answer"] not in {"A", "B", "C", "D"}:
                raise ValueError(f"Invalid gold answer for {source_id}: {record['answer']!r}")
            items.append(
                LongBenchItem(
                    index=index,
                    source_id=source_id,
                    local_task_id=f"longbench-v2-{source_id}",
                    record=record,
                )
            )
        return items

    def _select_split(self, items: list[LongBenchItem]) -> list[LongBenchItem]:
        if self.split == "full":
            return items
        if self.split == "parity":
            # Stratified subset for parity: every 3rd item within each
            # (domain, difficulty, length) stratum, in dataset order.
            from collections import defaultdict

            buckets: dict[tuple[str, str, str], list[LongBenchItem]] = defaultdict(list)
            for item in items:
                r = item.record
                buckets[(r["domain"], r["difficulty"], r["length"])].append(item)
            chosen: list[LongBenchItem] = []
            for key in sorted(buckets):
                chosen.extend(buckets[key][::3])
            chosen.sort(key=lambda item: item.index)
            return chosen
        raise ValueError(f"Unknown split: {self.split!r} (expected 'full' or 'parity')")

    def _filter_tasks(self, items: list[LongBenchItem]) -> list[LongBenchItem]:
        if not self.task_ids:
            return items
        requested = {t.strip() for t in self.task_ids if t.strip()}
        return [
            item
            for item in items
            if {item.local_task_id, item.source_id, str(item.index)} & requested
        ]

    # --------------------------------------------------------------- writing
    def _read_template(self, relative_path: str) -> str:
        return (self._TEMPLATE_DIR / relative_path).read_text(encoding="utf-8")

    def _copy_template(self, task_dir: Path) -> None:
        ignore = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc")
        for entry in self._TEMPLATE_DIR.iterdir():
            if entry.name in {".DS_Store", "__pycache__"}:
                continue
            destination = task_dir / entry.name
            if entry.is_dir():
                shutil.copytree(entry, destination, dirs_exist_ok=True, ignore=ignore)
            else:
                shutil.copy2(entry, destination)

    def _write_instruction(self, task_dir: Path, item: LongBenchItem) -> None:
        r = item.record
        context = str(r["context"])
        # task-template/instruction.md = official prompts/0shot.txt with the inline
        # <text> block replaced by a pointer to /app/context.txt.
        template = self._read_template("instruction.md")
        instruction = template.format(
            n_words=f"{len(context.split()):,}",
            domain=r["domain"],
            question=str(r["question"]).strip(),
            choice_a=str(r["choice_A"]).strip(),
            choice_b=str(r["choice_B"]).strip(),
            choice_c=str(r["choice_C"]).strip(),
            choice_d=str(r["choice_D"]).strip(),
        )
        (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")

    def _write_task_toml(self, task_dir: Path, item: LongBenchItem) -> None:
        r = item.record
        content = self._read_template("task.toml")
        content = content.replace("{task_id}", item.local_task_id)
        content = content.replace("{domain_slug}", self._DOMAINS[r["domain"]])
        content = content.replace("{difficulty}", str(r["difficulty"]))  # easy | hard
        content = content.replace("{length}", str(r["length"]))
        content = content.replace("{dataset_revision}", f"{DATA_REPO}@{DATA_REVISION}")
        content = content.replace("{upstream_code_revision}", f"{UPSTREAM_CODE_REPO}@{UPSTREAM_CODE_REVISION}")
        (task_dir / "task.toml").write_text(content, encoding="utf-8")

    def _write_environment(self, task_dir: Path, item: LongBenchItem) -> None:
        (task_dir / "environment" / "context.txt").write_text(
            str(item.record["context"]), encoding="utf-8"
        )

    def _write_tests(self, task_dir: Path, item: LongBenchItem) -> None:
        r = item.record
        expected = {
            "source_id": item.source_id,
            "answer": r["answer"],
            "domain": r["domain"],
            "sub_domain": r.get("sub_domain"),
            "difficulty": r["difficulty"],
            "length": r["length"],
            "dataset_revision": f"{DATA_REPO}@{DATA_REVISION}",
            "dataset_sha256": DATA_SHA256,
            "upstream_code_revision": f"{UPSTREAM_CODE_REPO}@{UPSTREAM_CODE_REVISION}",
        }
        (task_dir / "tests" / "expected.json").write_text(
            json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (task_dir / "tests" / "test.sh").chmod(0o755)

    def _write_solution(self, task_dir: Path, item: LongBenchItem) -> None:
        solve = self._read_template("solution/solve.sh").replace(
            "{answer}", item.record["answer"]
        )
        path = task_dir / "solution" / "solve.sh"
        path.write_text(solve, encoding="utf-8")
        path.chmod(0o755)

    def _write_task(self, item: LongBenchItem) -> None:
        task_dir = self.output_dir / item.local_task_id
        if task_dir.exists():
            if not self.overwrite:
                return
            shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True)
        self._copy_template(task_dir)
        self._write_instruction(task_dir, item)
        self._write_task_toml(task_dir, item)
        self._write_environment(task_dir, item)
        self._write_tests(task_dir, item)
        self._write_solution(task_dir, item)

    def run(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        items = self._filter_tasks(self._select_split(self._load_items()))
        if self.limit is not None:
            items = items[: max(0, self.limit)]
        for item in items:
            self._write_task(item)
        print(f"Generated {len(items)} LongBench v2 task(s) in {self.output_dir}")
