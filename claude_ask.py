"""
claude_ask.py - call the Anthropic API non-interactively for the automated pipeline.

Usage: python claude_ask.py PROMPT_FILE INPUT_FILE [INPUT_FILE ...]

Concatenates the prompt file and every input file into one message and sends
it to Claude. Tries the `ant auth login` OAuth profile first (no explicit key,
the bare client resolves it automatically), and only falls back to the
ANTHROPIC_API_KEY in .env if that path fails for any reason. Prints the reply
to stdout. Meant to fill in for a live Claude session in the scheduled
pipeline, the analyst pass and the merge step both call this.
"""

import argparse
import os
import sys

import anthropic

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192


def load_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values


def get_api_key():
    env_value = os.environ.get("ANTHROPIC_API_KEY")
    if env_value:
        return env_value
    return load_env_file(ENV_PATH).get("ANTHROPIC_API_KEY")


def build_message(prompt_file, input_files):
    with open(prompt_file, "r", encoding="utf-8") as f:
        parts = [f.read()]
    for path in input_files:
        label = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            parts.append(f"\n=== INPUT: {label} ===\n{f.read()}")
    return "\n".join(parts)


def send(client, message):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        # This model defaults to extended thinking, which otherwise eats the whole
        # max_tokens budget on reasoning and leaves nothing for the actual answer.
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": message}],
    )


def get_response(message):
    # Prefer the `ant auth login` OAuth profile: a bare client with no explicit
    # api_key resolves it automatically (env vars first, then the profile). If
    # that fails for any reason (no profile configured, expired refresh token,
    # billing), fall back to the ANTHROPIC_API_KEY in .env so the pipeline still
    # runs on whichever credential actually has funds.
    try:
        response = send(anthropic.Anthropic(), message)
        print("used ant auth login OAuth profile", file=sys.stderr)
        return response
    except Exception as e:
        print(f"OAuth profile failed ({e}), falling back to .env API key", file=sys.stderr)

    api_key = get_api_key()
    if not api_key:
        print("ANTHROPIC_API_KEY not set, add it to .env", file=sys.stderr)
        sys.exit(1)
    response = send(anthropic.Anthropic(api_key=api_key), message)
    print("used .env API key", file=sys.stderr)
    return response


def main():
    parser = argparse.ArgumentParser(description="Send a prompt plus input files to Claude and print the reply.")
    parser.add_argument("prompt_file", help="Markdown file with the instructions, e.g. prompt_claude.md")
    parser.add_argument("input_files", nargs="+", help="One or more files to append as input, e.g. packet.json")
    args = parser.parse_args()

    message = build_message(args.prompt_file, args.input_files)
    response = get_response(message)

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text:
        print(f"claude returned no text, stop_reason: {response.stop_reason}", file=sys.stderr)
        sys.exit(1)
    # Windows redirects stdout through the console codepage (cp1252) by default,
    # which can't encode emoji, force UTF-8 so redirected output survives intact.
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
