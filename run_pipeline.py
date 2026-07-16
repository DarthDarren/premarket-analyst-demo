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
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
ET = ZoneInfo("America/New_York")

# Task Scheduler runs with a bare environment, none of this is inherited the
# way an interactive shell has it. Node/npm for the codex CLI itself, and
# Git's own usr/bin and mingw64/bin for the coreutils codex-ask.sh relies on
# (mktemp, cat, rm), bash.exe alone does not bring those along non-interactively.
EXTRA_PATH_DIRS = [
    r"C:\Program Files\nodejs",
    os.path.expandvars(r"%APPDATA%\npm"),
    r"C:\Program Files\Git\usr\bin",
    r"C:\Program Files\Git\mingw64\bin",
]

LOG_FILE = None


def log(msg):
    ts = datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        LOG_FILE.write(line + "\n")
        LOG_FILE.flush()


def run(cmd, env, timeout=300):
    log(f"running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=SCRIPT_DIR, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timed out after {timeout}s: {' '.join(cmd)}")
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def run_capture_to_file(cmd, out_path, env, timeout=300):
    log(f"running: {' '.join(cmd)} > {os.path.basename(out_path)}")
    with open(out_path, "w", encoding="utf-8") as out:
        try:
            result = subprocess.run(cmd, cwd=SCRIPT_DIR, stdout=out, env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"timed out after {timeout}s: {' '.join(cmd)}")
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def run_codex_pass(prompt_path, packet_path, out_path, env, timeout=180):
    log("running: codex independent pass")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()
    with open(packet_path, "r", encoding="utf-8") as f:
        packet_text = f.read()
    combined = f"{prompt_text}\n\n=== INPUT: packet.json ===\n{packet_text}"

    with open(out_path, "w", encoding="utf-8") as out:
        try:
            result = subprocess.run(
                [BASH_EXE, CODEX_ASK],
                input=combined,
                stdout=out,
                text=True,
                cwd=SCRIPT_DIR,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"codex pass timed out after {timeout}s, likely hung rather than failed cleanly")
    if result.returncode != 0:
        raise RuntimeError("codex pass failed, rerun manually to see stderr")


def main():
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(EXTRA_PATH_DIRS + [env.get("PATH", "")])

    now_et = datetime.datetime.now(ET)
    date_str = now_et.date().isoformat()
    time_str = now_et.strftime("%I:%M %p").lstrip("0")
    stamp = f"{now_et.strftime('%A, %B %d, %Y')} - {time_str} ET"

    if now_et.weekday() >= 5:
        log(f"today ({now_et.strftime('%A')}) is a weekend, skipping")
        return

    # Two triggers point at this script now (a fixed morning time and a logon
    # trigger, since the fixed time alone has already been observed to silently
    # not fire at all on some days). This guard keeps a logon-triggered run from
    # duplicating a report and a second email on a day the morning trigger did fire.
    html_path = os.path.join(SCRIPT_DIR, "reports", f"premarket_{date_str}.html")
    if os.path.exists(html_path):
        log(f"already ran today, {html_path} exists, skipping")
        return

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
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"pipeline_{datetime.date.today().isoformat()}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        LOG_FILE = f
        try:
            main()
        except Exception as e:
            log(f"pipeline failed: {e}")
            sys.exit(1)
