#!/bin/bash
set -euo pipefail

mkdir -p /logs/verifier
python3 /tests/grade.py \
  --answer-file /app/answer.txt \
  --expected /tests/expected.json \
  --reward /logs/verifier/reward.txt \
  --result /logs/verifier/result.json
