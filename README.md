# Harbor Adapters

 [![](https://dcbadge.limes.pink/api/server/https://discord.gg/QVvyhRw5UQ)](https://discord.gg/QVvyhRw5UQ)
[![Docs](https://img.shields.io/badge/Docs-000000?style=for-the-badge&logo=mdbook&color=105864)](https://harborframework.com/docs)
[![Cookbook](https://img.shields.io/badge/Cookbook-000000?style=for-the-badge&logo=mdbook&color=105864)](https://github.com/harbor-framework/harbor-cookbook)
[![DOI](https://zenodo.org/badge/1032170083.svg)](https://doi.org/10.5281/zenodo.20953922)

Release blog: https://harbor-index.org/

Paper: https://arxiv.org/abs/2609.04298

---

This repository is the standalone home for **Harbor adapters** — the code that converts
external benchmarks (SWE-Bench, Aider Polyglot, GPQA, AIME, and 80+ more) into
[Harbor](https://github.com/harbor-framework/harbor)'s task format so they can be run, scored, and
shared through the Harbor harness. It was split out of the main
[`harbor-framework/harbor`](https://github.com/harbor-framework/harbor) monorepo so adapters can be
versioned and contributed independently.

Harbor itself — the CLI and evaluation framework — lives in
[`harbor-framework/harbor`](https://github.com/harbor-framework/harbor) and is an **external
dependency** of this repo (install with `uv tool install harbor`). See the
[Harbor docs](https://harborframework.com/docs) and the
[Harbor Cookbook](https://github.com/harbor-framework/harbor-cookbook) for the framework itself.

## What is an adapter?

An adapter translates a benchmark into Harbor **tasks**. Each generated task is a directory with:

- `task.toml` — configuration and metadata
- `instruction.md` — the natural-language task given to the agent
- `environment/` — Dockerfile / environment definition
- `tests/` — verification scripts (`test.sh` writes the reward to `/logs/verifier/reward.txt`)
- `solution/` (optional) — the oracle / reference solution

An adapter's job is to parse an upstream benchmark and emit those task directories reproducibly.

## Repository structure

```
adapters/
├── src/                       # one directory per adapter — the heart of this repo (85 adapters)
│   └── <adapter-name>/        # a self-contained, independent uv project
│       ├── pyproject.toml            # package name = "harbor-<adapter-name>-adapter"
│       ├── uv.lock                   # each adapter locks its own dependencies
│       ├── README.md                 # adapter docs (parity results, reproduction, notes)
│       ├── parity_experiment.json    # parity results vs. the original benchmark
│       ├── adapter_metadata.json     # adapter metadata
│       ├── <adapter-name>.yaml       # reference config for running the adapter
│       └── src/<adapter_name>/       # the Python package (dashes → underscores)
│           ├── adapter.py            # task-generation logic (<AdapterName>Adapter class)
│           ├── main.py               # CLI entry point (--output-dir/--limit/--overwrite/--task-ids)
│           └── task-template/        # task.toml, instruction.md, environment/, solution/, tests/
├── docs/                      # adapter authoring guides (see Documentation below)
├── skills/                    # Agent skills for adapter work
├── scripts/                   # Helper scripts (validation, parity summary)
└── .github/workflows/         # CI: adapter review + parity summary
```

Every adapter under `src/` is an **independent [uv](https://docs.astral.sh/uv/) project** with its
own `pyproject.toml` and `uv.lock`. There is no repo-wide virtualenv or lockfile — you work inside a
single adapter directory. This mirrors the layout described in
[`docs/adapters.mdx`](docs/adapters.mdx).

## Installation

Install the Harbor CLI (the harness that runs the tasks these adapters generate):

```bash
uv tool install harbor
# or: pip install harbor
```

## Using an adapter

Each adapter generates task directories you can then run with Harbor:

```bash
cd src/<adapter-name>
uv sync                                              # install this adapter's deps
uv run <adapter-name> --output-dir /path/to/output   # generate task directories
```

`uv run <adapter-name>` maps to `<adapter_name>.main:main` via the adapter's `[project.scripts]`.
Once the tasks exist, run them with the Harbor harness, e.g.:

```bash
harbor run -p /path/to/output -a claude-code -m "anthropic/claude-opus-5"
```

See a specific adapter's own `README.md` for its exact commands, parity results, and any special
setup.

## Creating a new adapter

Use the **create-adapter** skill in [`skills/create-adapter/`](skills/create-adapter/) — it scaffolds
the adapter with `harbor adapter init` and hands off to the authoritative spec,
[`docs/adapters.mdx`](docs/adapters.mdx). New adapters must live at `src/<adapter-name>/`.

Key conventions (enforced by [`scripts/validate_adapter.py`](scripts/validate_adapter.py)):

- `pyproject.toml` `name` = `harbor-<folder>-adapter`.
- `[project.scripts]` has `<folder> = "<adapter_name>.main:main"`.
- Adapter code lives at `src/<adapter_name>/` (dashes → underscores); `adapter.py` defines an
  `<AdapterName>Adapter` class whose `run(self)` writes tasks under `self.output_dir`.
- Task names must be stable across runs and unique / registry-safe.

## Parity and review tooling

Use [run-parity](skills/run-parity/SKILL.md) to plan and report matched experiments,
[parity diagnostics](docs/parity-diagnostics.md) to investigate anomalies, and
[upload-parity-experiments](skills/upload-parity-experiments/SKILL.md) to publish
authorized results. The [adapter specification](docs/adapters.mdx) remains the
acceptance contract.

Run the structural validator locally before submission:

```bash
python scripts/validate_adapter.py <adapter-name>
```

Request automated review by commenting `/review-adapter` on an adapter PR.
Owners, members, collaborators, and contributors can request it. The workflow
calls a pinned implementation in
[adapter-automation](https://github.com/harbor-index/adapter-automation).
The model secrets and invocation stay configured here; the shared workflow uses
the accepted validator and specification to inspect the submitted PR revision.

## Citation

If you use **Harbor adapters** in academic work, please cite the paper:

```bibtex
@misc{shi2026harbor,
  title         = {Harbor Adapters and Harbor-Index: Infrastructure and a Curated Meta-Dataset for Large-Scale Agentic Evaluation},
  author        = {Shi, Lin and Lin, Haowei and Zhu, Zixuan and Zhou, Xiaoyue and Li, Xiang and Lin, Xiangning and Deng, Yaxuan and Xu, Han and Li, Yuangang and Li, Shanda and Chen, Zizhao and Xing, Hanwen and Raj, Harsh and Chen, Bo and Shi, Quan and Dillmann, Steven and Gao, Yipeng and Khanna, Puneesh and Lu, Ruofan and Zhou, Chao Beyond and Yang, Michael and Zhang, Robert and Chai, Siyuan and Chang, Jiayu and Chen, Yizhao and Chen, Xiaokun and Dai, Yiwei and Yang, Wenting and Liu, Hange and Liu, Minghao and Wang, Zihan and others},
  year          = {2026},
  eprint        = {2609.04298},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/2609.04298}
}
```
