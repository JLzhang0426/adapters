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
  <https://huggingface.co/datasets/zai-org/LongBench-v2> (formerly
  `THUDM/LongBench-v2`; `data.json`, ungated).
- **Pinned revisions:** dataset `zai-org/LongBench-v2@2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`
  (`data.json` sha256 `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`,
  465,490,535 bytes); prompt + scorer `THUDM/LongBench@2e00731f8d0bff23dc4325161044d0ed8af94c1e`
  (`prompts/0shot.txt`, `pred.py::extract_answer`, `result.py`). Both are
  recorded in every task's `task.toml` `[metadata]` and `tests/expected.json`.
- **License:** MIT.
- **Original metric:** accuracy (overall and by difficulty/length), from the
  model's single response to a zero-shot prompt containing the full context.

Main adaptation choices: the context becomes a file (`/app/context.txt`) that
the agent reads with its own tools instead of an inline prompt; the question,
choices and required response format are the official `prompts/0shot.txt`
wording; the answer is written to `/app/answer.txt` and parsed with a verbatim
port of the official `extract_answer` (no extensions).

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

- Generates all 503 tasks from the pinned HF `data.json` (auto-downloaded at
  the pinned revision to `./.cache/longbench-v2/`, or pointed to with
  `LONGBENCH_V2_DATA` / `--data-path`); the file's sha256 is verified against
  the pin before any task is written, so task ids, content and the parity
  subset cannot drift (`--skip-checksum` opts out, for experiments only).
- Each task image is `python:3.12-slim` plus the context file; no services,
  no network, no model calls in the verifier.
- Deterministic verifier: `extract_answer` is a verbatim port of the official
  `pred.py::extract_answer` (same two regexes, nothing more), and reward
  follows `result.py`'s default accuracy (unparseable / missing answer = 0).
- `task.toml` metadata carries `domain`, `difficulty` (easy/hard) and `length`
  (short/medium/long) for per-split reporting; `tests/expected.json` carries
  the same plus `sub_domain`.
- `--split parity`: stratified subset (every 3rd item per
  domain × difficulty × length stratum, 176 tasks) for cheaper parity runs.
- Oracle writes the gold letter in the official response format.
- `scripts/summarize.py` reports attempted / scored / failed trial counts
  (failed trials listed with their cause) and accuracy both over scored trials
  and over attempted trials with failures counted as wrong, then the official
  difficulty/length splits plus domain.

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
dataset `_id`s, or dataset indices), `--split {full,parity}`, `--data-path`,
`--skip-checksum`. The data cache lives at `./.cache/longbench-v2/data.json`
relative to the working directory. The generated dataset is ~440 MB (contexts
dominate).

## How It Is Graded

`tests/grade.py` reads `/app/answer.txt` and applies `extract_answer`, a
verbatim port of the official `pred.py::extract_answer` at the pinned
revision: strip `*`, then match `The correct answer is \(([A-D])\)`, then
`The correct answer is ([A-D])`. There are no extensions — a bare letter
(`D`, `(D)`, `d.`) or a lowercase sentence scores 0, exactly as upstream.
Reward is 1.0 iff the extracted letter equals the gold letter; a missing or
unparseable answer scores 0 — the same as the default (uncompensated) accuracy
in the official `result.py`. Per-task `domain`/`difficulty`/`length`, the
parse `status` (`answered` / `unparseable_answer` / `missing_answer_file`) and
the pinned revisions are written to `/logs/verifier/result.json` so per-split
accuracy can be aggregated from a job directory.

Grader controls on a generated task (gold = D): official format → 1; wrong
letter → 0; missing file → 0; prose without the sentence → 0; `D`, `(D)`,
`d.` → 0; `The correct answer is D` → 1; `**The correct answer is (D)**` → 1.

## Oracle Verification

`solve.sh` writes `The correct answer is (<gold>)` to `/app/answer.txt`. A
`nop` run (no answer written) scores 0 on every task, confirming the grader is
not vacuous.

Oracle run over all 503 tasks with the final (verbatim-upstream) parser and
pinned dataset (local Docker, 2026-11-09, Harbor 0.25.0, 8 concurrent trials):

```text
longbench-v2 • oracle
┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃ Trials ┃ Exceptions ┃  Mean ┃
┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│    503 │          0 │ 1.000 │
└────────┴────────────┴───────┘
Total runtime: 47m 33s
```

`scripts/summarize.py` on the job directory:

```text
attempted trials : 503
scored trials    : 503
failed trials    : 0  (trial exceptions: 0, verifier without reward: 0)

accuracy (scored)                            n= 503  acc=100.00%
accuracy (attempted, failures = 0)           n= 503  acc=100.00%
  difficulty=easy / hard                     n= 192 / 311   acc=100.00%
  length=short / medium / long               n= 180 / 215 / 108   acc=100.00%
  (all six domains)                                         acc=100.00%

scored trials with unparseable/missing answers: 0
```

(An earlier run on 2026-11-06 with the previous parser also scored 503/503 in
24m 30s; the parser change only removes leniency, so the oracle format is
unaffected.)

## Comparison with Original Benchmark (Parity)

Parity has not been run yet. Planned setting (to be agreed with the Harbor
team): Scenario 2 (the original harness is a direct LLM call) — fork
`THUDM/LongBench` at the pinned revision and add a per-question runner for a
Harbor-supported CLI agent (Codex or Claude Code) using the same prompt and
answer file; run the same agent and model through Harbor; 3 runs each;
accuracy overall and by difficulty/length reported as mean ± sample SEM.
Because contexts reach 2M words, parity may use the `parity` split (176 tasks,
stratified); the README will state the subset if so.

**Two protocols, reported separately.** Upstream LongBench v2 is a
*single-call, truncated-context* setting: the whole context is placed in one
prompt and, if it exceeds the model's window, the middle is cut
(`pred.py`). This adapter is a *file-reading agent* setting: the agent reads
`/app/context.txt` with its own tools, possibly selectively, across many
calls. The comparison will therefore carry one row per protocol so the two are
never conflated: (a) *file-reading agent protocol* — the fork's runner drives
the same CLI agent against the same context file and prompt as Harbor does,
which is the apples-to-apples parity row; (b) *upstream single-call protocol*
— the unmodified `pred.py` numbers for the same model, reported alongside as
the reference the paper used, not as a parity target. Any gap between (a) and
(b) is a property of the protocol, not of the adapter.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| TBD (file-reading agent protocol, both sides) | TBD | Accuracy | 3 | TBD | TBD | TBD |
| upstream `pred.py` (single-call, truncated context) — reference only | TBD | Accuracy | 3 | TBD | TBD | n/a |

Reproduction requirements and steps:

```bash
# Original side (fork link to be added): per-question CLI-agent runner using prompts/0shot.txt
git clone https://github.com/THUDM/LongBench.git && cd LongBench && git checkout 2e00731f8d0bff23dc4325161044d0ed8af94c1e
python pred_agent.py --agent codex --model <model>    # added in the parity fork: file-reading agent protocol
python pred.py --model <model>                        # unmodified upstream: single-call, truncated-context reference
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
  selectively; this is an inherent protocol difference, which is why the parity
  section reports the file-reading agent protocol and the upstream single-call
  protocol as separate rows and uses the same agent on both sides for the
  former.
- **Pinned data.** The adapter refuses to build from a `data.json` whose
  sha256 differs from the pin (the HF repo was renamed from `THUDM` to
  `zai-org`; the old URL redirects, and the pinned commit is unaffected). The
  parity split is derived from dataset order, so the pin is what keeps it
  stable.
- **Long contexts are expensive.** p90 context ≈ 216k words, max ≈ 1.38M words
  (16 MB file). Agent timeout is 1 hour per task. Budget accordingly; use
  `--split parity` for cheaper experiments.
- **Dataset size:** ~440 MB of task directories.
- **Scoring variants.** The official `result.py` also reports a "compensated"
  accuracy that grants 0.25 for unparseable predictions; the verifier reports
  plain accuracy. The parser is the official one with no leniency; a
  bare-letter-tolerant variant, if ever wanted, should be a separately named
  dataset rather than a change to this one. CoT and RAG settings of the paper
  are not separate tasks (agents may reason however they like).
- Some contexts contain non-English text (e.g. a Kalamang grammar) and code
  repositories flattened to text, as in the original.

## Installation / Prerequisites

- Docker and Harbor (`uv tool install harbor`, ≥ 0.25).
- `cd src/longbench-v2 && uv sync`.
- ~500 MB disk for the dataset cache plus generated tasks.
- No API keys are needed for generation or oracle runs.

## Troubleshooting

- `unparseable_answer` in `result.json`: the agent did not write the exact
  sentence `The correct answer is (X)`; the verifier is exactly as strict as
  the original (bare letters are not accepted).
- `does not match the pinned LongBench v2 dataset`: the local `data.json`
  differs from the pinned revision; delete it to re-download, or pass
  `--skip-checksum` for a deliberately different file.
- Agent timeouts on `long` tasks: raise `[agent] timeout_sec` in `task.toml`
  via the adapter template, or use the `parity` split.
- Re-download data: delete `./.cache/longbench-v2/data.json` (relative to the
  working directory).

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
