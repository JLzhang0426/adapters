# Diagnose parity anomalies without changing the benchmark

Use these techniques when building, running, or reviewing parity experiments.
They do not add universal acceptance thresholds. Follow the benchmark's own
contract and the repository's [adapter specification](adapters.mdx).
For planning and execution, use the [run-parity skill](../skills/run-parity/SKILL.md).
Preserve each attempt and its configuration so another person can investigate it.

## A final stage has no input data

Inspect the full data handoff, not only the function that reports the error.
Check whether a dispatcher, allowlist, filter, task identifier, mount, or archive
path drops data before it reaches the evaluator. Compare both implementations.
Test the caller-to-evaluator boundary as well as the evaluator in isolation.

A skip reason indicating missing inputs may be correct for absent input
while the absence itself is a wiring defect. Determine whether the benchmark
intends that stage to be optional. Do not assume successful earlier experiments
mean that a later stage was fitted.

## Losses are null, non-finite, or unchanged

`null` is a serialization outcome, not a root cause. Trace the original value and
exception handling before JSON conversion. Separate a skipped fit, an unchanged
finite fit, a non-finite objective, an exception, and a worker timeout.

When a replay is authorized, preserve the exact submitted code, inputs, initial
parameters, evaluator version, and relevant worker limits. Reproduce in isolation
without replacing the final submission with a better intermediate candidate.
Inspect shapes, units, singular inputs, NaN/Inf propagation, subprocess exit
status, and swallowed exceptions. Compare the same input on both execution paths.

Attribute the result only as far as the evidence allows:

| Evidence | Supported conclusion |
| --- | --- |
| Invalid submitted code fails under both matched evaluators | Agent-code failure, subject to the benchmark's scoring contract |
| Valid expected input fails in both evaluators | Candidate shared evaluator limitation; reproduce against the intended contract |
| Same code and input work upstream but fail in Harbor | Candidate adaptation defect; isolate environment, handoff, and execution differences |
| Only a serialized null is available | Cause unresolved; obtain the pre-serialization error or a controlled replay |

Check effective runtime too: a nominal fit budget can differ from nested worker
timeouts, data size, dependency behavior, or actual elapsed time. Label any repair
as a new revision and validate it symmetrically; preserve historical results.

## Responses are empty or streams fail

HTTP 200 establishes request acceptance, not successful generation. Check the
endpoint's documented completion contract, terminal events, finish reason, usage,
and transport errors in final artifacts as well as live snapshots. An SSE `[DONE]`
marker is relevant only for protocols that use it.

A clean completion that exhausts the output budget without an answer is different
from a broken stream with no terminal result. Preserve budget-exhaustion outcomes
under the benchmark's existing policy; do not add silent retries. An empty answer
alone does not establish a context-window limit, provider fault, or adapter bug.
Report prompt, completion, and reasoning token counts separately when available.

## Long-running experiments and performance claims

If managing runs is in scope, identify the current scheduler before acting and
avoid duplicate launches. Follow the experiment's recorded hold and recovery
policy. Archive logs before provider retention expires; confirm ownership and
salvage evidence before terminating a dead sandbox. Local silence alone does not
prove a remote worker is stuck. These are operational safeguards, not a prescribed
scheduler, concurrency limit, or polling interval for every adapter.

For speed comparisons, distinguish full trial duration, model request latency,
time to first token, and fitting/tool time. State the token numerator and timed
interval for TPS, including whether reasoning tokens are counted. Keep completion
status and model/provider configuration visible. Different tokenizers and token
budgets limit cross-model TPS comparisons; faster TPS alone does not mean a trial
finishes sooner.

## Apply the checks to other adapters

Use the repository specification for acceptance criteria and pinned upstream code
for benchmark semantics. Follow required artifacts through dispatch and evaluation,
whether they are test reports, retrieved documents, predictions, or intermediate
results. Verify rubric claims against the implemented calculation and a minimal
example. Keep benchmark-specific score thresholds, budgets, and corrective changes
out of requirements for unrelated adapters.
