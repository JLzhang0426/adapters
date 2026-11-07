# LongBench v2 → Harbor Adapter

## Overview

[LongBench v2](https://longbench2.github.io) (THUDM, [arXiv:2412.15204](https://arxiv.org/abs/2412.15204))
measures deep understanding and reasoning over **long contexts** (8k to 2M
words) with **503 human-written, expert-reviewed multiple-choice questions**
(four options, one gold letter) across six task categories:

| Category | Tasks | | Difficulty | Tasks | | Length (words) | Tasks |
|---|---:|---|---|---:|---|---|---:|
| Single-Document QA | 175 | | easy | 192 | | short (<32k) | 180 |
| Multi-Document QA | 125 | | hard | 311 | | medium (32k–128k) | 215 |
| Long In-context Learning | 81 | | | | | long (>128k) | 108 |
| Long-dialogue History Understanding | 39 |
| Code Repository Understanding | 50 |
| Long Structured Data Understanding | 33 |

- **Adapter size:** 503 tasks (the full dataset; nothing excluded). A
  stratified `parity` split of 176 tasks is also available (`--split parity`).
- **Source:** <https://github.com/THUDM/LongBench>, data from
  <https://huggingface.co/datasets/THUDM/LongBench-v2> (`data.json`, ungated).
- **License:** MIT.
- **Original metric:** accuracy (overall and by difficulty/length), from the
  model's single response to a zero-shot prompt containing the full context.

Main adaptation choices: the context becomes a file (`/app/context.txt`) that
the agent reads with its own tools instead of an inline prompt; the question,
choices and required response format are the official `prompts/0shot.txt`
wording; the answer is written to `/app/answer.txt` and parsed with the official
`extract_answer` regexes (plus a bare-letter fallback).

## What is LongBench v2?

LongBench v2 is the successor to LongBench (ACL 2024). Its questions were
written by domain experts, then filtered so that even human experts with search
tools score only ~54% under a 15-minute limit, making it a benchmark for
*reasoning over* long inputs rather than retrieval. Contexts include academic
papers, legal/financial documents, novels, multi-document collections, code
repositories, tables, long dialogues, and grammar books for unseen languages.
The paper evaluates models in zero-shot, CoT and RAG settings; the headline
metric is zero-shot accuracy.

## Adapter Features

- Generates all 503 tasks from the pinned HF `data.json` (auto-downloaded to
  `.cache/longbench-v2/` or pointed to with `LONGBENCH_V2_DATA` / `--data-path`).
- Each task image is `python:3.12-slim` plus the context file; no services,
  no network, no model calls in the verifier.
- Deterministic verifier mirroring the official `pred.py::extract_answer`
  parsing and `result.py` accuracy (unparseable / missing answer = 0).
- `task.toml` metadata carries `domain`, `difficulty` (easy/hard) and `length`
  (short/medium/long) for per-split reporting; `tests/expected.json` carries
  the same plus `sub_domain`.
- `--split parity`: stratified subset (every 3rd item per
  domain × difficulty × length stratum, 176 tasks) for cheaper parity runs.
- Oracle writes the gold letter in the official response format.

## Generated Task Structure

```text
datasets/longbench-v2/
├── longbench-v2-66ead7bd5a08c7b9b35dca7a/
│   ├── task.toml
│   ├── instruction.md            # official 0-shot prompt + file pointers
│   ├── environment/
│   │   ├── Dockerfile            # python:3.12-slim, COPY context.txt /app/
│   │   └── context.txt           # the long context (8k–2M words)
│   ├── solution/
│   │   └── solve.sh              # writes "The correct answer is (X)" to /app/answer.txt
│   └── tests/
│       ├── expected.json         # gold letter + metadata
│       ├── grade.py              # official extract_answer logic
│       └── test.sh
└── ...
```

Task names are `thudm/longbench-v2__longbench-v2-<_id>` where `<_id>` is the
dataset record id.

Adapter source layout:

```text
src/longbench-v2/
├── README.md
├── adapter_metadata.json
├── parity_experiment.json
├── pyproject.toml
├── run_longbench-v2.yaml
└── src/longbench_v2/
    ├── adapter.py
    ├── main.py
    └── task-template/
```

## Run Evaluation / Harness

### Running with Datasets Registry

```bash
uv run harbor run -d longbench-v2                      # oracle
uv run harbor run -d longbench-v2 -a <agent> -m "<model>"
uv run harbor run -d longbench-v2@parity -a <agent> -m "<model>"   # once the parity tag is published
```

(Available once the dataset is registered in `harbor-datasets` / the registry.)

### Using Job Configurations

```bash
# From the adapters repository root
uv run --project src/longbench-v2 harbor run -c src/longbench-v2/run_longbench-v2.yaml -a <agent> -m "<model>"
uv run --project src/longbench-v2 harbor run -p datasets/longbench-v2 -a <agent> -m "<model>"
uv run harbor job resume -p /path/to/jobs/directory
```

### Running Individual Trial

```bash
uv run --project src/longbench-v2 harbor trial start -p datasets/longbench-v2/<task_id>            # oracle
uv run --project src/longbench-v2 harbor trial start -p datasets/longbench-v2/<task_id> -a <agent> -m "<model>"
```

## Usage: Create Task Directories

```bash
cd src/longbench-v2
uv sync
uv run longbench-v2 --output-dir ../../datasets/longbench-v2                    # all 503 tasks
uv run longbench-v2 --output-dir ../../datasets/longbench-v2 --split parity     # 176-task parity subset
uv run longbench-v2 --output-dir ../../datasets/longbench-v2 --task-ids 66ead7bd5a08c7b9b35dca7a
```

Flags: `--output-dir`, `--limit`, `--overwrite`, `--task-ids` (Harbor ids,
dataset `_id`s, or dataset indices), `--split {full,parity}`, `--data-path`.
The generated dataset is ~440 MB (contexts dominate).

## How It Is Graded

`tests/grade.py` reads `/app/answer.txt`, strips `*`, and applies the official
regexes in order: `The correct answer is \(([A-D])\)`, then
`The correct answer is ([A-D])`; as a fallback it accepts a bare letter
(`B`, `(B)`, `b.`). Reward is 1.0 iff the extracted letter equals the gold
letter; a missing or unparseable answer scores 0 — the same as the default
(uncompensated) accuracy in the official `result.json`. Per-task
`domain`/`difficulty`/`length` are written to `/logs/verifier/result.json` so
per-split accuracy can be aggregated from a job directory.

## Oracle Verification

`solve.sh` writes `The correct answer is (<gold>)` to `/app/answer.txt`. A
`nop` run (no answer written) scores 0 on every task, confirming the grader is
not vacuous.

Oracle run over all 503 tasks (local Docker, 2026-11-06, Harbor 0.25.0):

```text
longbench-v2 • oracle
┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃ Trials ┃ Exceptions ┃  Mean ┃
┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│    503 │          0 │ 1.000 │
└────────┴────────────┴───────┘
Total runtime: 24m 30s
```

`scripts/summarize.py` on the job directory reports 100% for every
difficulty, length and domain split, with 0 unparseable answers.

## Comparison with Original Benchmark (Parity)

Parity has not been run yet. Planned setting (to be agreed with the Harbor
team): Scenario 2 (the original harness is a direct LLM call) — fork
`THUDM/LongBench` and add a per-question runner for a Harbor-supported CLI agent
(Codex or Claude Code) using the same prompt and answer file; run the same agent
and model through Harbor; 3 runs each; accuracy overall and by
difficulty/length reported as mean ± sample SEM. Because contexts reach 2M
words, parity may use the `parity` split (176 tasks, stratified); the README
will state the subset if so.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| TBD | TBD | Accuracy | 3 | TBD | TBD | TBD |

Reproduction requirements and steps:

```bash
# Original side (fork link to be added): per-question CLI-agent runner using prompts/0shot.txt
git clone https://github.com/THUDM/LongBench.git && cd LongBench
python pred_agent.py --agent codex --model <model>    # added in the parity fork
python result.py

# Harbor side (from the adapters repository root)
uv run --project src/longbench-v2 longbench-v2 --output-dir datasets/longbench-v2 --split parity
uv run --project src/longbench-v2 harbor run -c src/longbench-v2/run_longbench-v2.yaml -a <agent> -m "<model>"
```

Accuracy = fraction of tasks with reward 1.0; per-split numbers come from
`domain`/`difficulty`/`length` in each trial's `verifier/result.json`.

## Notes & Caveats

- **Context as a file vs. inline prompt.** The original feeds the whole
  context into one prompt and truncates the middle if it exceeds the model's
  window. Harbor agents read `/app/context.txt` with tools and may read
  selectively; this is an inherent harness difference and the reason parity
  must use the same agent on both sides.
- **Long contexts are expensive.** p90 context ≈ 216k words, max ≈ 1.38M words
  (16 MB file). Agent timeout is 1 hour per task. Budget accordingly; use
  `--split parity` for cheaper experiments.
- **Dataset size:** ~440 MB of task directories.
- **Scoring variants.** The official `result.py` also reports a "compensated"
  accuracy that grants 0.25 for unparseable predictions; the verifier reports
  plain accuracy. CoT and RAG settings of the paper are not separate tasks
  (agents may reason however they like).
- Some contexts contain non-English text (e.g. a Kalamang grammar) and code
  repositories flattened to text, as in the original.

## Installation / Prerequisites

- Docker and Harbor (`uv tool install harbor`, ≥ 0.25).
- `cd src/longbench-v2 && uv sync`.
- ~500 MB disk for the dataset cache plus generated tasks.
- No API keys are needed for generation or oracle runs.

## Troubleshooting

- `unparseable_answer` in `result.json`: the agent wrote prose without the
  required format; the verifier is as lenient as the original plus bare letters.
- Agent timeouts on `long` tasks: raise `[agent] timeout_sec` in `task.toml`
  via the adapter template, or use the `parity` split.
- Re-download data: delete `.cache/longbench-v2/data.json`.

## Citation

```bibtex
@article{bai2024longbench2,
  title={LongBench v2: Towards Deeper Understanding and Reasoning on Realistic Long-context Multitasks},
  author={Yushi Bai and Shangqing Tu and Jiajie Zhang and Hao Peng and Xiaozhi Wang and Xin Lv and Shulin Cao and Jiazheng Xu and Lei Hou and Yuxiao Dong and Jie Tang and Juanzi Li},
  journal={arXiv preprint arXiv:2412.15204},
  year={2024}
}
```

## Authors & Contributions

This adapter is developed and maintained by [Jialin Zhang](mailto:jiz297@berkeley.edu).

**Issues and Contributions:**
- Submit Issues and Pull Requests to the main repository
- Follow the project's coding style and commit guidelines

## Acknowledgement

Parity API acknowledgement to be added once experiments are run with
team-provided keys.
