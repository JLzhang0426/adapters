#!/bin/bash
# Oracle: write the gold answer in the official response format.
set -euo pipefail
mkdir -p /app
printf 'The correct answer is (%s)\n' "{answer}" > /app/answer.txt
