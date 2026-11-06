#!/bin/bash
# Oracle solution: replay a pre-validated reference conversation.
#
# VitaBench ships no reference solutions (grading is a rubric-based LLM judge over
# the whole conversation), so the adapter stores one validated trajectory per task
# (see src/vita-bench/oracle/ and scripts/build_oracle.py). The trajectory is
# loaded into the vita-runtime sidecar (POST /state) so the verifier scores it
# with the official evaluator exactly like a live agent run; a local copy is also
# written as a fallback for the verifier.
set -euo pipefail

ORACLE="/solution/oracle_trajectory.json"
STATE_PATH="/logs/agent/vita_runtime_state.json"
RUNTIME_URL="${VITA_RUNTIME_URL:-http://vita-runtime:8000}"

if [ ! -f "${ORACLE}" ]; then
  echo "No oracle trajectory available for this task (${ORACLE} missing)." >&2
  exit 1
fi

mkdir -p "$(dirname "${STATE_PATH}")"
python3 - "${ORACLE}" "${STATE_PATH}" "${RUNTIME_URL}" <<'PYEOF'
import json
import sys
import urllib.request

oracle_path, state_path, runtime_url = sys.argv[1:4]
with open(oracle_path, encoding="utf-8") as fp:
    oracle = json.load(fp)

missing = {"messages", "termination_reason"} - set(oracle)
if missing:
    raise SystemExit(f"Oracle trajectory is missing fields: {sorted(missing)}")
if oracle["termination_reason"] not in {"agent_stop", "user_stop"}:
    raise SystemExit(
        f"Oracle trajectory has non-success termination: {oracle['termination_reason']}"
    )
oracle.setdefault("states", {"old_states": [], "new_states": []})
oracle["start_tool_called"] = True
oracle["oracle_replay"] = True

with open(state_path, "w", encoding="utf-8") as fp:
    json.dump(oracle, fp, indent=2, ensure_ascii=False)

body = json.dumps(oracle).encode("utf-8")
request = urllib.request.Request(
    f"{runtime_url}/state", data=body, method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=60) as response:
    print("runtime:", response.read().decode("utf-8"))
print(f"Replayed oracle trajectory with {len(oracle['messages'])} messages.")
PYEOF
