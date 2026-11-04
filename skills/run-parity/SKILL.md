---
name: run-parity
description: Help adapter authors plan, run, diagnose, and report matched upstream and Harbor parity experiments under the adapter contract.
---

# Run matched parity experiments

Read [the adapter specification](../../docs/adapters.mdx), especially Steps 3–6,
before planning execution. It owns the acceptance criteria, schemas, ramp-up
sequence, and reporting rules. This skill helps carry them out; it does not
change benchmark prompts, scoring, or acceptance requirements.

## Establish the experiment

Record the adapter and upstream code revisions, dataset revision and selection,
Harbor revision, agent and model versions, and effective settings on both sides.
Compare prompts, tools, budgets, timeouts, dependencies, and launch commands.
Record differences and their implications before interpreting the scores.

Confirm task generation and oracle verification as required by the specification.
Oracle success and upstream-versus-Harbor parity establish different things.

Before launching experiments, establish the authorized task set, cost budget,
concurrency, output location, and stopping/recovery policy. Planning or reviewing
artifacts does not itself authorize paid runs. Check for existing runs before
launching replacements.

## Run and preserve evidence

Follow the specification's symmetric execution order: sanity-check 5–10 tasks
on both sides, complete one full run on both sides, then scale to three runs on
both sides. Keep the selected tasks and effective configuration fixed across
repetitions. Record any corrective change as a new experiment revision.

Keep an attempt ledger connecting each side, task, seed/repetition,
configuration, completion status, score, and artifact location. Preserve genuine
agent failures under the benchmark's scoring policy. Record infrastructure
failures separately; do not invent scores for missing results or silently retry
failures and select the better result.

When results diverge or execution fails, use the specification's debug playbook
and [parity diagnostics](../../docs/parity-diagnostics.md). Diagnose the smallest
relevant example before scaling experiments. Preserve original evidence and
apply corrections symmetrically.

## Report the experiment

Populate `parity_experiment.json` and the README using the specification's
schemas. Derive means and sample SEM from the raw run arrays, with consistent
units. Check the required overlap of run-score ranges; overlapping SEM intervals
alone do not satisfy that criterion. Keep oracle results separate from parity.

Include reproducible commands, pinned revisions, artifact links, costs, and
unresolved limitations. Run the local structural validator before submission;
a structural pass alone does not establish benchmark fidelity or parity.

When publishing artifacts is authorized, use
[upload-parity-experiments](../upload-parity-experiments/SKILL.md) and record the
resulting parity PR URL.
