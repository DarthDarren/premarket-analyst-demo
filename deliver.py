"""
deliver.py - email the rendered HTML premarket report via Resend.

Usage: python deliver.py reports/premarket_<date>.html
"""

import argparse
import os
import re

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
DEFAULT_EMAIL_FROM = "AI Premarket Analyst <onboarding@resend.dev>"
RESEND_URL = "https://api.resend.com/emails"


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


def get_config():
    # Real environment variables win over whatever is in the .env file.
    file_values = load_env_file(ENV_PATH)
    config = {}
    for key in ("RESEND_API_KEY", "EMAIL_TO", "EMAIL_FROM"):
        env_value = os.environ.get(key)
        config[key] = env_value if env_value else file_values.get(key)
    return config


def extract_date(html_path):
    match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(html_path))
    return match.group(1) if match else None


def send_report(html_path):
    config = get_config()
    api_key = config.get("RESEND_API_KEY")
    email_to = config.get("EMAIL_TO")
    email_from = config.get("EMAIL_FROM") or DEFAULT_EMAIL_FROM

    if not api_key or not email_to:
        print("email skipped, set RESEND_API_KEY + EMAIL_TO")
        return

    if not os.path.exists(html_path):
        print(f"email skipped, file not found: {html_path}")
        return

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    date_str = extract_date(html_path)
    subject = f"AI Premarket Report - {date_str}" if date_str else "AI Premarket Report"

    to_list = [addr.strip() for addr in email_to.split(",") if addr.strip()]

    payload = {
        "from": email_from,
        "to": to_list,
        "subject": subject,
        "html": html_content,
    }

    try:
        resp = requests.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
    except Exception as e:
        print(f"email failed, request error: {e}")
        return

    if resp.ok:
        print(f"email sent to {email_to}, subject: {subject}")
    else:
        print(f"email failed, resend returned {resp.status_code}: {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="Email the rendered HTML premarket report via Resend.")
    parser.add_argument("html_file", help="Path to the rendered HTML report, e.g. reports/premarket_2026-07-10.html")
    args = parser.parse_args()

    try:
        send_report(args.html_file)
    except Exception as e:
        print(f"email skipped, unexpected error: {e}")


if __name__ == "__main__":
    main()
