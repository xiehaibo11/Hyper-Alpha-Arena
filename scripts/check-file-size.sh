#!/usr/bin/env bash
set -euo pipefail

max_lines="${1:-500}"

rg --files \
  -g '*.py' \
  -g '*.ts' \
  -g '*.tsx' \
  -g '*.js' \
  -g '*.jsx' \
  -g '!node_modules/**' \
  -g '!frontend/dist/**' \
  -g '!backend/static/**' \
  -g '!data/**' \
  -g '!logs/**' \
  -g '!venv/**' \
  | while IFS= read -r file; do
    lines="$(wc -l < "$file" | tr -d ' ')"
    if [ "$lines" -gt "$max_lines" ]; then
      printf '%6s %s\n' "$lines" "$file"
    fi
  done \
  | sort -nr
