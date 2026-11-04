# AGENTS.md — Harbor Adapters

This repository is the standalone collection of **Harbor benchmark adapters**, migrated out of the
[Harbor](https://github.com/harbor-framework/harbor) monorepo. An adapter converts an existing
benchmark into Harbor's task format so it can be run by the Harbor harness.

Harbor itself (the CLI / framework) is an **external dependency** — it is not vendored here.
Install it with `uv tool install harbor`; this repo contains only adapters, their docs, skills, and CI.

## Repository Structure

```
adapters/
├── src/                     # One directory per adapter (the adapter packages)
│   └── <adapter-name>/
│       ├── pyproject.toml            # Package: name = "harbor-<adapter-name>-adapter"
│       ├── README.md                 # Adapter documentation (machine-parsed sections)
│       ├── parity_experiment.json    # Parity results (present once parity is recorded)
│       ├── adapter_metadata.json     # Adapter metadata
│       ├── uv.lock                   # Locked dependencies (each adapter is its own uv project)
│       ├── <adapter-name>.yaml       # Reference config for running the adapter
│       └── src/<adapter_name>/       # Python package (dashes → underscores)
│           ├── __init__.py
│           ├── adapter.py            # Task-generation logic
│           ├── main.py               # CLI entry point (--output-dir, --limit, --overwrite, --task-ids)
│           └── task-template/        # task.toml, instruction.md, environment/, solution/, tests/
├── docs/                    # Adapter documentation (see below)
├── skills/                  # Claude Code skills for adapter work
├── scripts/                 # CI helper scripts
└── .github/workflows/       # CI (adapter review, parity summary)
```

Each adapter under `src/` is an **independent uv project** with its own `pyproject.toml` and
`uv.lock`. There is no repo-wide virtualenv or lockfile — work inside a single adapter directory.

## What an Adapter Produces

An adapter generates Harbor **task directories**, each defined by:

- `task.toml` — configuration and metadata (must set `name` under `[task]`)
- `instruction.md` — natural-language task description for the agent
- `environment/` — Dockerfile / environment definition
- `tests/` — verification scripts (`test.sh` writes reward to `/logs/verifier/reward.txt`)
- `solution/` (optional) — oracle / reference solution

## Working With an Adapter

```bash
cd src/<adapter-name>
uv sync                                   # install this adapter's deps
uv run <adapter-name> --output-dir /path/to/output   # generate task directories
```

`uv run <adapter-name>` maps to `<adapter_name>.main:main` via `[project.scripts]`.

## Creating a New Adapter

Use the **create-adapter** skill (`skills/create-adapter/`). The authoritative spec is
`docs/adapters.mdx` — read it in full before implementing. New adapters must land at
`src/<adapter-name>/`.

Package conventions (enforced by `scripts/validate_adapter.py`):

- `pyproject.toml` `name` = `harbor-<folder>-adapter` (folder name with dashes).
- `[project.scripts]` has `<folder> = "<adapter_name>.main:main"`.
- Code lives at `src/<adapter_name>/` (dashes → underscores); `adapter.py` defines a
  `<AdapterName>Adapter` class with a `run(self)` method writing tasks under `self.output_dir`.
- Task names must be stable across runs and unique/registry-safe.

## Documentation

- `docs/adapters.mdx` — comprehensive adapter spec (the "Agent Guide"; the contract for building adapters).
- `docs/adapters-human.mdx` — concise human walkthrough.
- `docs/parity-diagnostics.md` — help with investigating parity failures and unexpected results.

> Note: these docs were migrated from the Harbor monorepo docs site and are pending a dedicated
> content pass; some cross-links and paths may still reference the old monorepo layout.

## Skills

- `skills/create-adapter/` — scaffold and guide a new adapter build.
- `skills/review-adapter/` — review your adapter using the same guide as CI.
- `skills/run-parity/` — plan, run, diagnose, and report matched parity experiments.
- `skills/upload-parity-experiments/` — publish parity/oracle result folders to the
  `harborframework/parity-experiments` Hugging Face dataset.

## CI / Automation

Located in `.github/workflows/`:

- `adapter-review.yml` — structural validation + AI review. Triggered by a `/review-adapter`
  comment on a PR (from an owner/member/collaborator/contributor). Runs
  `scripts/validate_adapter.py` on the adapters touched by the PR (detected under `src/`), then an
  AI review against the adapter spec. It calls the shared workflow in
  `harbor-index/adapter-automation` at a pinned commit. The existing API key and endpoint
  are passed from this repository's secrets.
- `update-parity-summary.yml` — on push to the default branch touching any
  `src/*/parity_experiment.json`, regenerates the repo-root `parity_summary.csv` via
  `scripts/generate_parity_summary.py` and commits it.

Helper scripts:

- `scripts/validate_adapter.py` — structural/compliance checks. Usage: `python scripts/validate_adapter.py <adapter-name>` (resolves to `src/<adapter-name>`).
- `scripts/generate_parity_summary.py` — aggregates every `src/*/parity_experiment.json` into `parity_summary.csv`.

## Important Notes

- Python 3.11+ / `uv` for package management.
- Migration principle: do **not** change a benchmark's prompts or scoring/grading logic when
  adapting; adjustments are limited to structure, packaging, entry points, and paths.
- Adapter PRs now live in `harbor-framework/adapters`; historical adapter PRs may reference
  `harbor-framework/harbor` and remain valid.
- Dataset generation output is registered separately (via `harbor-datasets` / the registry); this
  repo holds adapter code, not the generated datasets.
