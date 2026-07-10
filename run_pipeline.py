"""
run_pipeline.py - runs the full daily premarket pipeline end to end.

scan.py -> Claude's analyst pass -> Codex's independent pass -> merge ->
render to HTML -> email delivery. Meant to be launched by Windows Task
Scheduler every weekday morning, but works fine run by hand too.
"""

import datetime
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe")
BASH_EXE = r"C:\Program Files\Git\usr\bin\bash.exe"
CODEX_ASK = os.path.join(os.path.expanduser("~"), ".claude", "bin", "codex-ask.sh")
ET = ZoneInfo("America/New_York")

# Task Scheduler runs with a bare environment, node/npm/codex need to be on
# PATH explicitly, they won't be inherited the way an interactive shell has them.
EXTRA_PATH_DIRS = [
    r"C:\Program Files\nodejs",
    os.path.expandvars(r"%APPDATA%\npm"),
]


def log(msg):
    ts = datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run(cmd, env):
    log(f"running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def run_capture_to_file(cmd, out_path, env):
    log(f"running: {' '.join(cmd)} > {os.path.basename(out_path)}")
    with open(out_path, "w", encoding="utf-8") as out:
        result = subprocess.run(cmd, cwd=SCRIPT_DIR, stdout=out, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def run_codex_pass(prompt_path, packet_path, out_path, env):
    log("running: codex independent pass")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()
    with open(packet_path, "r", encoding="utf-8") as f:
        packet_text = f.read()
    combined = f"{prompt_text}\n\n=== INPUT: packet.json ===\n{packet_text}"

    with open(out_path, "w", encoding="utf-8") as out:
        result = subprocess.run(
            [BASH_EXE, CODEX_ASK],
            input=combined,
            stdout=out,
            text=True,
            cwd=SCRIPT_DIR,
            env=env,
        )
    if result.returncode != 0:
        raise RuntimeError("codex pass failed, see reports log or rerun manually to see stderr")


def main():
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(EXTRA_PATH_DIRS + [env.get("PATH", "")])

    now_et = datetime.datetime.now(ET)
    date_str = now_et.date().isoformat()
    time_str = now_et.strftime("%I:%M %p").lstrip("0")
    stamp = f"{now_et.strftime('%A, %B %d, %Y')} - {time_str} ET"

    log("=== pipeline start ===")

    log("step 1: scan.py")
    run([VENV_PYTHON, "scan.py"], env)

    log("step 2: claude analyst pass")
    run_capture_to_file(
        [VENV_PYTHON, "claude_ask.py", "prompt_claude.md", "packet.json"],
        os.path.join(SCRIPT_DIR, "claude_view.md"),
        env,
    )

    log("step 3: codex independent pass")
    run_codex_pass(
        os.path.join(SCRIPT_DIR, "prompt_codex.md"),
        os.path.join(SCRIPT_DIR, "packet.json"),
        os.path.join(SCRIPT_DIR, "codex_view.md"),
        env,
    )

    log("step 4: merge")
    stamp_path = os.path.join(SCRIPT_DIR, "today_stamp.txt")
    with open(stamp_path, "w", encoding="utf-8") as f:
        f.write(f"Today's date and time for the date line: {stamp}\n")
    run_capture_to_file(
        [
            VENV_PYTHON, "claude_ask.py", "prompt_merge.md",
            "packet.json", "claude_view.md", "codex_view.md", "today_stamp.txt",
        ],
        os.path.join(SCRIPT_DIR, "REPORT.md"),
        env,
    )
    os.remove(stamp_path)

    log("step 5: render to HTML")
    run([VENV_PYTHON, "render_report.py", "REPORT.md", date_str], env)

    log("step 6: email delivery")
    run([VENV_PYTHON, "deliver.py", f"reports/premarket_{date_str}.html"], env)

    log("=== pipeline complete ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"pipeline failed: {e}")
        sys.exit(1)
