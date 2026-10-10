"""
watchlist_universe.py - the tickers the watchlist screens run on.

Reads the newest watchlist_merged_*.csv that the Screener project's
merge_watchlists.py writes (TradingView lists plus IBKR positions, tiered).
Screener stays its own project, this only reads its output. If no CSV can be
found, the last list read is used from a local cache so the morning run
still has a universe.

Folder: $PREMARKET_WATCHLIST_DIR if set, otherwise ../Screener/output next to
this repo.
"""

import csv
import glob
import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "Screener", "output")
CACHE_PATH = os.path.join(SCRIPT_DIR, ".watchlist_cache.json")
FILE_PATTERN = "watchlist_merged_*.csv"
STALE_AFTER_DAYS = 7


def watchlist_dir():
    return os.environ.get("PREMARKET_WATCHLIST_DIR") or DEFAULT_DIR


def yahoo_symbol(row):
    # TradingView writes BRK.B where Yahoo wants BRK-B.
    symbol = (row.get("symbol") or row.get("ticker", "").split(":")[-1]).strip().upper()
    return symbol.replace(".", "-")


def file_timestamp(path):
    m = re.search(r"(\d{8})_(\d{6})", os.path.basename(path))
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def read_csv(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tier = (row.get("suggested_tier") or "").strip()
            if not tier or tier == "exclude":
                continue
            rows.append({
                "ticker": yahoo_symbol(row),
                "tv_ticker": row.get("ticker", ""),
                "tier": tier,
                "source_lists": [x for x in (row.get("source_lists") or "").split(";") if x],
                "owned": (row.get("owned") or "").strip().upper() == "Y",
            })
    # One row per Yahoo symbol, first one wins.
    seen, unique = set(), []
    for r in rows:
        if r["ticker"] and r["ticker"] not in seen:
            seen.add(r["ticker"])
            unique.append(r)
    return unique


def load(log=print):
    """Returns (rows, info). rows is empty only when there's no CSV and no cache."""
    folder = watchlist_dir()
    files = sorted(glob.glob(os.path.join(folder, FILE_PATTERN)))
    info = {"folder": folder}

    if files:
        path = files[-1]
        try:
            rows = read_csv(path)
            stamp = file_timestamp(path)
            info.update({"source_file": os.path.basename(path), "loaded_from": "csv",
                         "list_date": stamp.isoformat() if stamp else None})
            try:
                with open(CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump({"info": info, "rows": rows}, f, indent=2)
            except OSError as e:
                log(f"watchlist cache write failed: {e}")
            return rows, _finish(rows, info)
        except Exception as e:
            log(f"watchlist csv read failed for {path}: {e}")
            info["error"] = f"could not read {os.path.basename(path)}: {e}"
    else:
        info["error"] = f"no {FILE_PATTERN} found in {folder}"

    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cached = json.load(f)
        info.update({k: cached["info"].get(k) for k in ("source_file", "list_date")})
        info["loaded_from"] = "cache"
        return cached["rows"], _finish(cached["rows"], info)
    except (OSError, ValueError, KeyError):
        info["loaded_from"] = "none"
        return [], _finish([], info)


def _finish(rows, info):
    tiers = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    info["tickers"] = len(rows)
    info["tiers"] = tiers
    if info.get("list_date"):
        age = (datetime.now() - datetime.fromisoformat(info["list_date"])).days
        info["list_age_days"] = age
        info["stale"] = age > STALE_AFTER_DAYS
    return info
