"""
render_report.py - turn a markdown premarket report into a clean HTML page.

Usage: python render_report.py REPORT.md [YYYY-MM-DD]
"""

import argparse
import datetime
import os

import markdown

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 40px 20px;
    background: #f4f4f2;
    color: #222;
    font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
    line-height: 1.6;
}
.page {
    max-width: 900px;
    margin: 0 auto;
    background: #ffffff;
    border: 1px solid #e2e2e0;
    border-radius: 8px;
    padding: 48px 56px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
h1, h2, h3, h4 {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    color: #111;
}
h1 {
    font-size: 1.9rem;
    margin: 0 0 4px 0;
}
h1 + h3 {
    margin-top: 0;
    font-weight: 400;
    color: #666;
    font-size: 1rem;
}
h2 {
    font-size: 1.3rem;
    margin-top: 2.2em;
    margin-bottom: 0.6em;
    padding-bottom: 6px;
    border-bottom: 2px solid #eee;
}
h3 {
    color: #444;
    font-size: 1.05rem;
}
p { margin: 0.8em 0; }
a { color: #2a5db0; }
blockquote {
    margin: 1.2em 0;
    padding: 12px 18px;
    background: #f7f5ee;
    border-left: 4px solid #cbb98a;
    color: #555;
    font-size: 0.95rem;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1.2em 0;
    font-size: 0.92rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
th, td {
    padding: 8px 10px;
    border: 1px solid #e2e2e0;
    text-align: left;
    vertical-align: top;
}
th {
    background: #eeeeec;
    font-weight: 600;
    color: #222;
}
tbody tr:nth-child(even) td { background: #fafaf8; }
ul, ol { padding-left: 1.4em; }
li { margin: 0.3em 0; }
hr {
    border: none;
    border-top: 1px solid #e2e2e0;
    margin: 2em 0;
}
code {
    background: #f2f2ef;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.9em;
}
pre {
    background: #f2f2ef;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
}
footer {
    margin-top: 3em;
    padding-top: 1em;
    border-top: 1px solid #e2e2e0;
    font-size: 0.85rem;
    color: #888;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    text-align: center;
}
"""

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="page">
{body}
<footer>{footer}</footer>
</div>
</body>
</html>
"""


def extract_title(md_text):
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "Premarket Report"


def format_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    except ValueError:
        return date_str


def render(markdown_path, date_str):
    with open(markdown_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    title = extract_title(md_text)
    body_html = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    footer = f"Generated {format_date(date_str)} · Built by Claude + Codex · Educational only, not financial advice"

    page = PAGE_TEMPLATE.format(title=title, css=CSS, body=body_html, footer=footer)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"premarket_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)

    return out_path


def main():
    parser = argparse.ArgumentParser(description="Render a markdown premarket report to a clean HTML page.")
    parser.add_argument("markdown_file", help="Path to the markdown report, e.g. REPORT.md")
    parser.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD, defaults to today")
    args = parser.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    out_path = render(args.markdown_file, date_str)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
