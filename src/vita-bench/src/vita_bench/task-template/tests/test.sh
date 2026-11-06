#!/bin/bash
set -euo pipefail

mkdir -p /logs/verifier

export VITABENCH_ROOT="${VITABENCH_ROOT:-/opt/vitabench}"
export VITA_MODEL_CONFIG_PATH="${VITA_MODEL_CONFIG_PATH:-/opt/vita_models.yaml}"

python3 /tests/evaluate.py \
  --config /tests/config.json \
  --runtime-log /logs/agent/vita_runtime_state.json \
  --reward /logs/verifier/reward.txt \
  --result /logs/verifier/result.json
