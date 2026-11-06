# VitaBench → Harbor Adapter

## Overview

[VitaBench](https://github.com/meituan-longcat/vitabench) (ICLR 2026) evaluates
LLM agents as customer-service assistants for everyday **life services**: food
delivery, in-store consumption and online travel (OTA). The agent talks to a
simulated user in a multi-turn conversation and operates the platform through
API tools over realistic databases (1,300+ service providers, ~7,000 products,
past transactions). Tasks are built from real user requests and require
temporal/spatial reasoning, large tool sets (66 tools in the cross-scenario
environment), proactive clarification of ambiguous requests, and tracking of
shifting user intent.

- **Task type**: multi-turn tool-use with a simulated user (Tau-bench style)
- **Language**: English task set (`tasks_en.json`; the Chinese originals are
  also in the upstream repo but are not adapted)
- **Task sets / adapter size**: 400 tasks = `delivery` (100) + `instore` (100)
  + `ota` (100) + `cross_domain` (100). The cross-scenario split is the paper's
  headline split (best models ≈ 32.5%); the single-scenario splits are its
  secondary results. No tasks are excluded.
- **Original repo / paper**: <https://github.com/meituan-longcat/vitabench>,
  <https://arxiv.org/abs/2509.26490>; pinned commit
  `742e240855bf8686a0842360749d5ea970ea3987`
- **License**: MIT
- **Scoring**: the official rubric-based sliding-window LLM evaluator; binary
  per-task reward (1.0 only if every rubric is met)

Main adaptation choices: the original environment, user simulator and evaluator
run **unmodified** (the pinned `vita` package is installed in the containers);
the conversation loop is exposed through an MCP sidecar instead of the in-process
`Orchestrator`, and the agent system prompt becomes `instruction.md`.

## What is VitaBench?

VitaBench ("Vita" = life) was built by Meituan's LongCat team to measure how well
agents handle versatile interactive tasks in real applications. Each scenario
(delivery / in-store / OTA) ships a database and a toolkit of read, write and
general tools; scenarios can be composed into one cross-scenario environment.
A task gives the simulated user a persona and instructions (e.g. "order mild
rice noodles to my hospital department, no fried or high-purine food, arriving
by 12:00"), and the agent must complete it through conversation and tool calls.
The evaluator walks the trajectory with a sliding window and marks each rubric
as met/unmet; the task reward is 1 only when all rubrics are met. The paper
reports success rate (average reward) per task set.

## Adapter Features

- Generates all 400 English tasks from a pinned upstream checkout (auto-cloned
  into `.cache/vitabench` if `VITABENCH_ROOT` is not set).
- Each task runs a `vita-runtime` MCP sidecar hosting the original environment
  (tools + database) and the original `UserSimulator`; the 66/20/24/38 domain
  tools are exposed 1:1 as MCP tools alongside `start_conversation`,
  `send_message_to_user`, `end_conversation`, etc.
- The verifier rebuilds the official `SimulationRun` from the recorded
  conversation and calls `vita.evaluator.evaluate_simulation` (evaluation type
  `trajectory`, the upstream default) with a configurable evaluator model.
- Ships `vita-llm-agent`, a parity agent that runs the upstream `LLMAgent`
  (same system prompt, tool schemas and raw-HTTP `generate`) inside the task
  container against the MCP runtime, with upstream seed derivation per trial.
- Oracle solutions are pre-validated trajectories (the benchmark ships no
  reference solutions); see "Oracle solutions" below.

## Generated Task Structure

```text
datasets/vita-bench/
├── vita-delivery-10711001/
│   ├── task.toml
│   ├── instruction.md               # upstream agent system prompt + MCP usage notes
│   ├── environment/
│   │   ├── Dockerfile               # python:3.12 + pinned vita package (agent + verifier)
│   │   ├── docker-compose.yaml      # adds the vita-runtime sidecar
│   │   └── runtime-server/
│   │       ├── Dockerfile
│   │       ├── server.py            # MCP server wrapping Environment + UserSimulator
│   │       ├── vita_models_config.py
│   │       └── task_config.json     # task environment/user scenario (no rubrics)
│   ├── solution/
│   │   ├── solve.sh                 # replays oracle_trajectory.json
│   │   └── oracle_trajectory.json   # present once the oracle has been built
│   └── tests/
│       ├── config.json              # full task incl. evaluation_criteria
│       ├── evaluate.py              # official evaluator wrapper
│       ├── vita_models_config.py
│       └── test.sh
├── vita-instore-…/
├── vita-ota-…/
└── vita-cross-…/
```

Task names are `meituan-longcat/vita-bench__vita-<set>-<source_id>` with
`<set>` ∈ `delivery`, `instore`, `ota`, `cross`.

Adapter source layout:

```text
src/vita-bench/
├── README.md
├── adapter_metadata.json
├── parity_experiment.json
├── pyproject.toml
├── run_vita-bench.yaml              # reference parity job config
├── vita_llm_agent.py                # Harbor agent wrapper (vita-llm-agent)
├── run_vita_llm_agent.py            # in-container runner driving upstream LLMAgent
├── scripts/build_oracle.py          # collects passing trajectories into oracle/
├── oracle/<task_set>/<id>.json      # validated oracle trajectories
└── src/vita_bench/
    ├── adapter.py
    ├── main.py
    └── task-template/
```

## Run Evaluation / Harness

### Running with Datasets Registry

```bash
uv run harbor run -d vita-bench                      # oracle
uv run harbor run -d vita-bench -a <agent> -m "<model>"
```

(Available once the dataset is registered in `harbor-datasets` / the registry.)

### Using Job Configurations

All runs need an OpenAI-compatible endpoint for the user simulator and the
evaluator (and for `vita-llm-agent`):

```bash
export OPENAI_API_KEY=...            # key for the endpoint below
export OPENAI_BASE_URL=https://.../v1 # chat/completions is appended automatically
export VITA_USER_MODEL=gpt-4.1       # user simulator (upstream default)
export VITA_EVALUATOR_MODEL=...      # rubric evaluator
```

```bash
# From the adapters repository root: full parity configuration (3 trials)
PYTHONPATH="$PWD/src/vita-bench" uv run --project src/vita-bench harbor run -c src/vita-bench/run_vita-bench.yaml

# Any Harbor agent on the locally generated dataset
uv run --project src/vita-bench harbor run -p datasets/vita-bench -a <agent> -m "<model>"

# Parity agent with a different model
PYTHONPATH="$PWD/src/vita-bench" uv run --project src/vita-bench harbor run \
  -p datasets/vita-bench --agent-import-path vita_llm_agent:VitaLLMAgent -m "openai/gpt-4.1"
```

`run_vita-bench.yaml` lists `vita_llm_agent` three times with
`vita_trial_index: 0/1/2` and `n_attempts: 1`. Upstream `vita run --num-trials 3`
seeds `random` with 300 and draws one seed per trial; the agent reproduces that
derivation so each Harbor trial uses the same seed as the corresponding upstream
trial (passed to both the agent LLM and the user simulator).

Optional environment variables: `VITA_USER_LLM_ARGS_JSON`,
`VITA_EVALUATOR_LLM_ARGS_JSON` (JSON merged into the generated `models.yaml`
entry, e.g. `{"max_tokens": 32768, "thinking": {"type": "enabled", "budget_tokens": 16384}}`).

### Running Individual Trial

```bash
uv run --project src/vita-bench harbor trial start -p datasets/vita-bench/vita-delivery-10711001            # oracle
uv run --project src/vita-bench harbor trial start -p datasets/vita-bench/vita-delivery-10711001 -a <agent> -m "<model>"
```

## Usage: Create Task Directories

```bash
cd src/vita-bench
uv sync
uv run vita-bench --output-dir ../../datasets/vita-bench            # all 400 tasks
uv run vita-bench --output-dir ../../datasets/vita-bench --task-ids cross_domain:A0812003 10711001
```

Flags: `--output-dir`, `--limit`, `--overwrite`, `--task-ids` (Harbor ids such as
`vita-cross-a0812003`, source ids, or `<task_set>:<source_id>`). Set
`VITABENCH_ROOT=/path/to/vitabench` to reuse an existing checkout; otherwise the
pinned commit is cloned into `.cache/vitabench`.

## How It Is Graded

The sidecar writes every message (assistant text, tool calls, tool results,
user messages) to `/logs/agent/vita_runtime_state.json`. The verifier parses it
into upstream `AssistantMessage`/`UserMessage`/`ToolMessage` objects, builds a
`SimulationRun`, and calls `evaluate_simulation(evaluation_type="trajectory")`:
rubrics from `expected_states[*].state_rubrics` and `overall_rubrics` are judged
over sliding windows of 10 messages (overlap 2) by the evaluator LLM; reward is
1.0 iff all rubrics are met. Conversations that never terminate, hit `max_steps`
(300) or `max_errors` (10), or produce invalid agent messages score 0, exactly
as upstream. Per-rubric verdicts are saved to `/logs/verifier/result.json`.
If the evaluator endpoint fails, the verifier exits non-zero (errored trial)
instead of recording a false 0.

## Oracle solutions

VitaBench has no reference solutions. Following the adapter spec for such
benchmarks, oracle trajectories are produced by running agents over the tasks,
keeping conversations scored 1.0 (confirmed by re-scoring), and completing the
rest with stronger models plus human review:

```bash
PYTHONPATH="$PWD/src/vita-bench" uv run --project src/vita-bench harbor run -c src/vita-bench/run_vita-bench.yaml
python src/vita-bench/scripts/build_oracle.py jobs/<job-id> --min-passes 2
uv run vita-bench --output-dir datasets/vita-bench --overwrite   # re-generate with oracle files
uv run --project src/vita-bench harbor run -p datasets/vita-bench -a oracle
```

`solution/solve.sh` replays the stored trajectory into the runtime state file;
the verifier then scores it with the official evaluator like any agent run.

**Status:** oracle trajectories are not yet built (requires API access; see
Notes & Caveats).

## Comparison with Original Benchmark (Parity)

Parity has not been run yet. Planned setting (to be confirmed with the Harbor
team): `vita-llm-agent` with the same model on both sides, user simulator
`gpt-4.1` (upstream default), identical evaluator model, 3 trials, all 400 tasks,
metric = average reward (success rate) per task set and overall, reported as
mean ± sample SEM over trials.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| vita-llm-agent@1.0 | TBD | Average Reward | 3 | 400 tasks | TBD | TBD |

Reproduction (original side): clone the pinned commit, create `models.yaml` with
the same endpoint/model entries the adapter generates (see
`task-template/environment/runtime-server/vita_models_config.py`), then

```bash
vita run --domain delivery --user-llm gpt-4.1 --agent-llm <model> --evaluator-llm <evaluator> \
  --language english --num-trials 3 --max-concurrency 8
# repeat for instore, ota and delivery,instore,ota (cross-scenario)
```

Harbor side: `harbor run -c src/vita-bench/run_vita-bench.yaml` as above.

## Notes & Caveats

- **LLM-judged, stochastic grading.** Both the user simulator and the evaluator
  are LLMs; expect run-to-run variance. Parity therefore compares means ± SEM
  over ≥3 trials with identical user/evaluator models on both sides.
- **Endpoint compatibility.** Upstream `generate()` POSTs directly to
  `base_url` and merges every `models.yaml` key (including `base_url`,
  `headers`, `max_input_tokens`) into the request body. Strict endpoints that
  reject unknown fields will fail on both the original and the adapter; use the
  same proxy for both sides.
- **Upstream default evaluator** is `anthropic.claude-3.7-sonnet` (internal
  Meituan model name); the adapter requires `VITA_EVALUATOR_MODEL` to be set to
  a model available on your endpoint. Parity must use the same evaluator on
  both sides.
- **Verifier cost/time.** Long conversations produce many evaluation windows
  (each an LLM call); the verifier timeout is 30 min.
- **Reward is binary** and rubric counts range from ~9 (delivery) to ~24
  (cross-scenario) per task, so expected scores are low (paper: ≤32.5% on
  cross-scenario for the best models).
- Tasks with a pre-existing `message_history` are not supported by the runtime
  (none exist in the current release).
- Chinese task set and the separate VitaBench-2.0 repository are out of scope.

## Installation / Prerequisites

- Docker and Harbor (`uv tool install harbor`, ≥ 0.25).
- `cd src/vita-bench && uv sync`.
- An OpenAI-compatible endpoint (`OPENAI_API_KEY`, `OPENAI_BASE_URL`) serving
  the user-simulator, evaluator and agent models.
- Images are built from `python:3.12-slim` and clone the pinned upstream commit
  (≈ 50 MB incl. data); no GPU needed.

## Troubleshooting

- `Conversation has already ended` from MCP tools: the agent kept calling tools
  after `###STOP###`/user stop; nothing to fix, the verifier scores what was
  recorded.
- `conversation_not_terminated` in `result.json`: the agent never ended the
  conversation (no `###STOP###`, no `end_conversation`). Reward is 0 as in the
  original harness when `max_steps` is reached.
- `evaluator_error` / non-zero verifier exit: evaluator endpoint unreachable or
  rejected the request; check `OPENAI_BASE_URL`, model name and
  `/logs/verifier/result.json`.
- Sidecar unhealthy on start: `docker compose logs vita-runtime` inside the trial
  directory; the most common cause is a missing `task_config.json` (regenerate).

## Citation

```bibtex
@article{he2025vitabench,
  title={VitaBench: Benchmarking LLM Agents with Versatile Interactive Tasks in Real-world Applications},
  author={He, Wei and Sun, Yueqing and Hao, Hongyan and Hao, Xueyuan and Xia, Zhikang and Gu, Qi and Han, Chengcheng and Zhao, Dengchang and Su, Hui and Zhang, Kefeng and Gao, Man and Su, Xi and Cai, Xiaodong and Cai, Xunliang and Yang, Yu and Zhao, Yunke},
  journal={arXiv preprint arXiv:2509.26490},
  year={2025}
}
```

## Authors & Contributions

This adapter is developed and maintained by [Jialin Zhang](mailto:jiz297@berkeley.edu).

**Issues and Contributions:**
- Submit Issues and Pull Requests to the main repository
- Follow the project's coding style and commit guidelines

## Acknowledgement

The runtime/verifier design follows the `tau3-bench` adapter. Parity API
acknowledgement to be added once experiments are run with team-provided keys.
