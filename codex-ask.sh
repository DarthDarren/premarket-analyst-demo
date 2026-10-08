#!/usr/bin/env bash
set -uo pipefail

if [ "$#" -ge 1 ]; then
    PROMPT="$1"
else
    PROMPT="$(cat)"
fi

OUT_FILE="$(mktemp)"
LOG_FILE="$(mktemp)"

# Prompt goes over stdin, not as an argv string, a large packet.json blows past the
# OS command line length limit if passed as a positional argument.
# Pin the model: the global ~/.codex/config.toml default drifted to a model that
# ChatGPT-account logins reject (400), which silently broke the scheduled pipeline.
# Override with CODEX_MODEL if this one is ever retired.
printf '%s' "$PROMPT" | codex exec --skip-git-repo-check -s read-only -m "${CODEX_MODEL:-gpt-5.6-sol}" -o "$OUT_FILE" - > "$LOG_FILE" 2>&1

if [ -s "$OUT_FILE" ]; then
    cat "$OUT_FILE"
    rm -f "$OUT_FILE" "$LOG_FILE"
    exit 0
else
    cat "$LOG_FILE" >&2
    rm -f "$OUT_FILE" "$LOG_FILE"
    exit 1
fi
