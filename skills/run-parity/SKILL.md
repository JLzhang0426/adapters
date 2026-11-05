---
name: run-parity
description: Help adapter authors plan, run, diagnose, and report matched upstream and Harbor parity experiments under the adapter contract.
---

# Run matched parity experiments

Read [the adapter specification](../../docs/adapters.mdx), especially Steps 3–6,
before planning the runs. Follow its acceptance criteria, schemas, required run
order, and reporting rules. Preserve the benchmark's prompts and scoring.

## Establish the experiment

Record the adapter and upstream code revisions, dataset revision and selected tasks,
Harbor revision, agent and model versions, and effective settings on both sides.
Compare prompts, tools, budgets, timeouts, dependencies, and launch commands.
Record differences and their implications before interpreting the scores.

Check task generation and run oracle verification as the specification requires.
An oracle pass does not establish parity between upstream and Harbor.

Before launching experiments, agree on the task set, spending limit, concurrency,
output location, and when to stop or retry. Get authorization before starting
paid runs. Check for existing runs before launching replacements.

## Run and preserve evidence

Follow the specification's run order: sanity-check 5–10 tasks
on both sides, complete one full run on both sides, then scale to three runs on
both sides. Keep the selected tasks and effective configuration fixed across
repetitions. Record any corrective change as a new experiment revision.

For each attempt, record the side, task, seed or repetition, configuration,
completion status, score, and result files. Keep genuine agent failures in the
scores as the benchmark requires. Record infrastructure failures separately.
Do not invent scores for missing results or silently retry failures and keep
the better result.

When results diverge or execution fails, use the specification's debug playbook
and [parity diagnostics](../../docs/parity-diagnostics.md). Diagnose the smallest
relevant example before scaling experiments. Preserve original evidence and
apply corrections symmetrically.

## Report the experiment

Populate `parity_experiment.json` and the README using the specification's
schemas. Calculate means and sample SEM from the raw run arrays, with consistent
units. Check the required overlap of run-score ranges; overlapping SEM intervals
alone do not satisfy that criterion. Keep oracle results separate from parity.

Include reproducible commands, pinned revisions, artifact links, costs, and
unresolved limitations. Run the local structural validator before submission;
a structural pass alone does not establish benchmark fidelity or parity.

When publishing artifacts is authorized, use
[upload-parity-experiments](../upload-parity-experiments/SKILL.md) and record the
resulting parity PR URL.
