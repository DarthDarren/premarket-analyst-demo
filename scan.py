"""
scan.py - premarket data gatherer.

Collects raw premarket data into packet.json. This file does ZERO analysis.
No conviction, no buckets, no opinions, just numbers and headlines. All
judgment happens later in the AI prompts that read packet.json.

Only keyless, free sources: yfinance, feedparser, requests. zoneinfo is stdlib.
"""

import json
import os
import re
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import feedparser
import requests
import yfinance as yf

ET = ZoneInfo("America/New_York")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKET_PATH = os.path.join(SCRIPT_DIR, "packet.json")
ECON_CACHE_FILE = os.path.join(SCRIPT_DIR, ".econ_calendar_cache.json")
ECON_CACHE_TTL_SECONDS = 4 * 60 * 60

MARKET_INSTRUMENTS = {
    "S&P 500": "^GSPC",
    "Dow": "^DJI",
    "Nasdaq": "^IXIC",
    "Russell 2000": "^RUT",
    "VIX": "^VIX",
    "US 10Y": "^TNX",
    "US 3M": "^IRX",
    "WTI Oil": "CL=F",
    "Dollar (DXY)": "DX-Y.NYB",
}

STATIC_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "SMCI", "MRVL", "TSLA", "AAPL", "MSFT", "META", "AMZN",
    "GOOGL", "NFLX", "DELL", "SNOW", "PLTR", "COIN", "MSTR", "SOFI", "RIVN", "NIO",
    "MARA", "RIOT", "BA", "DIS", "JPM", "BAC", "XOM", "CVX", "HOOD", "UBER",
    "CRWD", "PANW", "CELH", "LULU", "NKE", "CAVA", "DKNG", "ARM", "INTC", "MU",
]

RSS_FEEDS = {
    "MarketWatch Top": "http://feeds.marketwatch.com/marketwatch/topstories/",
    "MarketWatch RealTime": "http://feeds.marketwatch.com/marketwatch/realtimeheadlines/",
    "CNBC": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "Google News Markets": "https://news.google.com/rss/search?q=markets+OR+earnings+when:1d&hl=en-US&gl=US&ceid=US:en",
}

SPAM_PATTERNS = [
    re.compile(r"price prediction", re.IGNORECASE),
    re.compile(r"20\d{2}-20\d{2}"),
]

PRIMARY_PUBLISHERS = [
    "bloomberg", "reuters", "cnbc", "marketwatch", "barron",
    "yahoo finance", "wsj", "wall street journal",
]

# Generic words that show up across many unrelated company names. A word here can
# never count as a catalyst match on its own, e.g. "Applied" alone would match both
# Applied Optoelectronics and Applied Digital, so it takes the real ticker or a
# distinctive token to confirm a headline is actually about this company.
NAME_STOP = {
    "the", "inc", "corp", "corporation", "holdings", "technologies", "group",
    "digital", "applied", "advanced", "strategy", "motors", "energy",
    "platforms", "systems", "international", "industries", "solutions",
    "global", "capital", "partners", "ventures", "labs", "networks",
    "communications", "resources", "enterprises", "company", "co",
}

ECON_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

GAP_FILTER_MIN_ABS_GAP_PCT = 4.0
GAP_FILTER_MIN_PRICE = 3.0
GAP_FILTER_TOP_N = 12

DAY_RULES = {
    "min_gap_pct": 3.0,
    "min_price": 3.0,
    "min_market_cap": 1_000_000_000,
    "min_rvol": 1.5,
}

SWING_RULES = {
    "min_gap_pct": 8.0,
    "min_price": 3.0,
    "min_market_cap": 800_000_000,
}


def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# 1. Market snapshot
# ---------------------------------------------------------------------------

def get_market_snapshot():
    snapshot = {}
    for name, symbol in MARKET_INSTRUMENTS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if len(hist) < 2:
                raise ValueError("fewer than 2 daily bars returned")
            last = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            change_pct = (last - prev_close) / prev_close * 100
            snapshot[name] = {
                "symbol": symbol,
                "last": round(last, 4),
                "prev_close": round(prev_close, 4),
                "change_pct": round(change_pct, 4),
            }
            log(f"market snapshot ok: {name}")
        except Exception as e:
            log(f"market snapshot failed for {name} ({symbol}): {e}")
            snapshot[name] = {
                "symbol": symbol,
                "last": None,
                "prev_close": None,
                "change_pct": None,
                "error": str(e),
            }
    return snapshot


# ---------------------------------------------------------------------------
# 2. Live top movers, with static universe fallback
# ---------------------------------------------------------------------------

def fetch_screener(query_name):
    try:
        res = yf.screen(query_name, count=100)
        return res.get("quotes", []) if isinstance(res, dict) else []
    except Exception as e:
        log(f"screener {query_name} failed: {e}")
        return []


def normalize_quote(q):
    symbol = q.get("symbol")
    if not symbol:
        return None
    price = q.get("regularMarketPrice")
    prev_close = q.get("regularMarketPreviousClose")
    gap_pct = q.get("regularMarketChangePercent")
    if gap_pct is None and price is not None and prev_close:
        gap_pct = (price - prev_close) / prev_close * 100
    return {
        "ticker": symbol,
        "name": q.get("longName") or q.get("shortName") or symbol,
        "price": price,
        "prev_close": prev_close,
        "gap_pct": gap_pct,
        "market_cap": q.get("marketCap"),
        "volume": q.get("regularMarketVolume"),
    }


def get_live_movers():
    quotes = []
    for query_name in ("day_gainers", "most_actives"):
        quotes.extend(fetch_screener(query_name))
    movers = {}
    for q in quotes:
        norm = normalize_quote(q)
        if norm and norm["ticker"] not in movers:
            movers[norm["ticker"]] = norm
    log(f"live screeners returned {len(movers)} unique names")
    return list(movers.values())


def get_static_universe_movers():
    movers = []
    for ticker in STATIC_UNIVERSE:
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d")
            if len(hist) < 2:
                continue
            price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            gap_pct = (price - prev_close) / prev_close * 100
            try:
                fi = dict(yf.Ticker(ticker).fast_info)
            except Exception:
                fi = {}
            movers.append({
                "ticker": ticker,
                "name": ticker,
                "price": round(price, 4),
                "prev_close": round(prev_close, 4),
                "gap_pct": round(gap_pct, 4),
                "market_cap": fi.get("marketCap"),
                "volume": fi.get("lastVolume"),
            })
            log(f"static universe ok: {ticker}")
        except Exception as e:
            log(f"static universe failed for {ticker}: {e}")
    return movers


# ---------------------------------------------------------------------------
# 3. Gap filter
# ---------------------------------------------------------------------------

def filter_gappers(movers):
    filtered = []
    for m in movers:
        gap = m.get("gap_pct")
        price = m.get("price")
        if gap is None or price is None:
            continue
        if abs(gap) >= GAP_FILTER_MIN_ABS_GAP_PCT and price >= GAP_FILTER_MIN_PRICE:
            filtered.append(m)
    filtered.sort(key=lambda m: abs(m["gap_pct"]), reverse=True)
    return filtered[:GAP_FILTER_TOP_N]


# ---------------------------------------------------------------------------
# 4. Market wide RSS news
# ---------------------------------------------------------------------------

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def is_spam(title):
    if not title:
        return True
    return any(pat.search(title) for pat in SPAM_PATTERNS)


def fetch_rss_news():
    articles = []
    for source_name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            kept = 0
            for entry in feed.entries:
                title = (entry.get("title") or "").strip()
                if not title or is_spam(title):
                    continue
                summary = strip_html(entry.get("summary") or entry.get("description") or "")
                articles.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary,
                    "link": entry.get("link", ""),
                    "published": entry.get("published") or entry.get("updated") or "",
                })
                kept += 1
            log(f"rss ok: {source_name} ({kept} kept)")
        except Exception as e:
            log(f"rss failed for {source_name}: {e}")
    return articles


# ---------------------------------------------------------------------------
# 5. Economic calendar, cached, defensive
# ---------------------------------------------------------------------------

def load_econ_cache():
    try:
        if os.path.exists(ECON_CACHE_FILE):
            with open(ECON_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log(f"econ cache read failed: {e}")
    return None


def save_econ_cache(raw_data):
    try:
        payload = {"fetched_at": datetime.now(ET).isoformat(), "data": raw_data}
        with open(ECON_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as e:
        log(f"econ cache write failed: {e}")


def empty_econ_calendar(today_date, tomorrow_date, error):
    return {
        "source": ECON_CALENDAR_URL,
        "filter": "USD, High impact",
        "today_date": today_date.isoformat(),
        "tomorrow_date": tomorrow_date.isoformat(),
        "today": [],
        "tomorrow": [],
        "error": error,
    }


def fetch_econ_calendar_inner():
    now = datetime.now(ET)
    today_date = now.date()
    tomorrow_date = today_date + timedelta(days=1)

    note = None
    raw_data = None
    cache = load_econ_cache()

    if cache:
        try:
            fetched_at = datetime.fromisoformat(cache["fetched_at"])
            age = (now - fetched_at).total_seconds()
            if age < ECON_CACHE_TTL_SECONDS:
                raw_data = cache["data"]
                log(f"econ calendar: using cache ({int(age)}s old)")
        except Exception as e:
            log(f"econ cache parse failed: {e}")

    if raw_data is None:
        try:
            resp = requests.get(ECON_CALENDAR_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            raw_data = resp.json()
            save_econ_cache(raw_data)
            log("econ calendar: live fetch ok")
        except Exception as e:
            log(f"econ calendar live fetch failed: {e}")
            if cache and cache.get("data"):
                raw_data = cache["data"]
                note = f"live fetch failed ({e}), fell back to cached week from {cache.get('fetched_at')}"
                log("econ calendar: using stale cache as fallback")
            else:
                return empty_econ_calendar(today_date, tomorrow_date, f"no live data and no cache: {e}")

    today_events = []
    tomorrow_events = []
    for event in raw_data:
        if event.get("country") != "USD" or event.get("impact") != "High":
            continue
        try:
            event_dt = datetime.fromisoformat(event["date"]).astimezone(ET)
        except Exception:
            continue
        record = {
            "time_et": event_dt.strftime("%H:%M"),
            "title": event.get("title", ""),
            "forecast": event.get("forecast", ""),
            "previous": event.get("previous", ""),
        }
        if event_dt.date() == today_date:
            today_events.append((event_dt, record))
        elif event_dt.date() == tomorrow_date:
            tomorrow_events.append((event_dt, record))

    today_events.sort(key=lambda pair: pair[0])
    tomorrow_events.sort(key=lambda pair: pair[0])

    result = {
        "source": ECON_CALENDAR_URL,
        "filter": "USD, High impact",
        "today_date": today_date.isoformat(),
        "tomorrow_date": tomorrow_date.isoformat(),
        "today": [record for _, record in today_events],
        "tomorrow": [record for _, record in tomorrow_events],
    }
    if note:
        result["note"] = note
    return result


def fetch_econ_calendar():
    try:
        return fetch_econ_calendar_inner()
    except Exception as e:
        log(f"econ calendar failed hard, returning empty calendar: {e}")
        now = datetime.now(ET)
        return empty_econ_calendar(now.date(), now.date() + timedelta(days=1), f"unexpected failure: {e}")


# ---------------------------------------------------------------------------
# 6. Per gapper enrichment
# ---------------------------------------------------------------------------

def build_name_tokens(name):
    if not name:
        return []
    tokens = re.split(r"[\s,\.]+", name)
    return [
        tok for tok in (t.strip() for t in tokens)
        if tok and len(tok) >= 4 and tok.lower() not in NAME_STOP
    ]


def headline_matches_ticker(text, ticker, name_tokens):
    if not text:
        return False
    if re.search(r"\b" + re.escape(ticker) + r"\b", text):
        return True
    for tok in name_tokens:
        if re.search(r"\b" + re.escape(tok) + r"\b", text, re.IGNORECASE):
            return True
    return False


def publisher_rank(source_name):
    lname = (source_name or "").lower()
    for i, pub in enumerate(PRIMARY_PUBLISHERS):
        if pub in lname:
            return i
    return len(PRIMARY_PUBLISHERS)


def get_yf_news_for_ticker(ticker):
    try:
        news = yf.Ticker(ticker).news or []
    except Exception as e:
        log(f"yfinance news failed for {ticker}: {e}")
        return []
    out = []
    for n in news:
        content = n.get("content", {}) if isinstance(n, dict) else {}
        title = content.get("title") or n.get("title")
        if not title or is_spam(title):
            continue
        provider = content.get("provider") or {}
        publisher = provider.get("displayName") if isinstance(provider, dict) else ""
        canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = canonical.get("url", "") if isinstance(canonical, dict) else ""
        out.append({
            "title": title,
            "publisher": publisher or "",
            "link": link,
            "summary": strip_html(content.get("summary") or ""),
            "source": "yfinance",
        })
    return out


def get_catalyst_headlines(ticker, name, rss_articles):
    name_tokens = build_name_tokens(name)
    candidates = get_yf_news_for_ticker(ticker)
    for a in rss_articles:
        text = f"{a['title']} {a['summary']}"
        if headline_matches_ticker(text, ticker, name_tokens):
            candidates.append({
                "title": a["title"],
                "publisher": a["source"],
                "link": a["link"],
                "summary": a["summary"],
                "source": "rss",
            })

    seen = set()
    deduped = []
    for c in candidates:
        key = c["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    deduped.sort(key=lambda c: publisher_rank(c.get("publisher", "")))
    return deduped


def get_intraday_levels(ticker):
    empty = {"vwap": None, "hod": None, "lod": None, "premarket_high": None, "premarket_volume": None}
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m", prepost=True)
    except Exception as e:
        log(f"intraday bars failed for {ticker}: {e}")
        return {**empty, "error": str(e)}
    if hist.empty:
        return {**empty, "error": "no intraday bars returned"}

    hist = hist.copy()
    if hist.index.tz is not None:
        hist.index = hist.index.tz_convert(ET)
    premarket = hist[hist.index.time < dt_time(9, 30)]

    typical_price = (hist["High"] + hist["Low"] + hist["Close"]) / 3
    total_vol = hist["Volume"].sum()
    vwap = float((typical_price * hist["Volume"]).sum() / total_vol) if total_vol > 0 else None

    return {
        "vwap": round(vwap, 4) if vwap is not None else None,
        "hod": round(float(hist["High"].max()), 4) if not hist["High"].empty else None,
        "lod": round(float(hist["Low"].min()), 4) if not hist["Low"].empty else None,
        "premarket_high": round(float(premarket["High"].max()), 4) if not premarket.empty else None,
        "premarket_volume": float(premarket["Volume"].sum()) if not premarket.empty else None,
    }


def get_daily_metrics(ticker):
    empty = {"sma_200": None, "prior_day_high": None, "prior_close": None, "avg_volume_20": None, "today_open": None}
    try:
        hist = yf.Ticker(ticker).history(period="1y", interval="1d")
    except Exception as e:
        log(f"daily bars failed for {ticker}: {e}")
        return {**empty, "error": str(e)}
    if hist.empty:
        return {**empty, "error": "no daily bars returned"}

    today_str = datetime.now(ET).date().isoformat()
    today_open = None
    if hist.index[-1].date().isoformat() == today_str:
        today_row = hist.iloc[-1]
        if today_row["Open"] == today_row["Open"]:  # NaN check without importing pandas
            today_open = float(today_row["Open"])
        hist = hist.iloc[:-1]  # drop today's partial bar, it is not a finished day yet

    if hist.empty:
        return {**empty, "today_open": today_open, "error": "no prior daily bars after excluding today"}

    if today_open is None:
        try:
            fi = dict(yf.Ticker(ticker).fast_info)
            today_open = fi.get("open")
        except Exception:
            today_open = None

    return {
        "sma_200": round(float(hist["Close"].tail(200).mean()), 4),
        "prior_day_high": round(float(hist["High"].iloc[-1]), 4),
        "prior_close": round(float(hist["Close"].iloc[-1]), 4),
        "avg_volume_20": round(float(hist["Volume"].tail(20).mean()), 2),
        "today_open": round(float(today_open), 4) if today_open is not None else None,
    }


def compute_rvol(today_volume, avg_volume_20):
    # yfinance reports close to 0 premarket volume through this keyless path, so a true
    # premarket RVOL needs a premarket feed like Alpaca. Full-day volume over the 20-day
    # average is the keyless stand-in used here, not a real premarket read.
    if not today_volume or not avg_volume_20:
        return None
    return round(today_volume / avg_volume_20, 4)


def get_next_earnings_date(ticker):
    try:
        cal = yf.Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            return sorted(dates)[0].isoformat()
    except Exception as e:
        log(f"earnings date failed for {ticker}: {e}")
    return None


def compute_eligibility(gapper):
    gap_pct = gapper.get("gap_pct")
    price = gapper.get("price")
    market_cap = gapper.get("market_cap")
    rvol = gapper.get("rvol")
    catalyst_found = gapper.get("catalyst_found")
    daily = gapper.get("daily_metrics") or {}
    prior_day_high = daily.get("prior_day_high")
    today_open = daily.get("today_open")
    sma_200 = daily.get("sma_200")

    try:
        day_eligible = bool(
            gap_pct is not None and gap_pct > DAY_RULES["min_gap_pct"]
            and price is not None and price > DAY_RULES["min_price"]
            and market_cap is not None and market_cap > DAY_RULES["min_market_cap"]
            and rvol is not None and rvol > DAY_RULES["min_rvol"]
            and price is not None and prior_day_high is not None and price > prior_day_high
        )
    except Exception:
        day_eligible = False

    try:
        swing_eligible = bool(
            gap_pct is not None and gap_pct >= SWING_RULES["min_gap_pct"]
            and price is not None and price > SWING_RULES["min_price"]
            and today_open is not None and prior_day_high is not None and today_open > prior_day_high
            and today_open is not None and sma_200 is not None and today_open > sma_200
            and market_cap is not None and market_cap >= SWING_RULES["min_market_cap"]
            and bool(catalyst_found)
        )
    except Exception:
        swing_eligible = False

    return day_eligible, swing_eligible


def enrich_gapper(gapper, rss_articles):
    ticker = gapper["ticker"]
    log(f"enriching {ticker}")

    enriched = dict(gapper)
    catalysts = get_catalyst_headlines(ticker, gapper.get("name"), rss_articles)
    enriched["catalyst_found"] = len(catalysts) > 0
    enriched["catalyst_headlines"] = catalysts[:5]
    enriched["intraday_levels"] = get_intraday_levels(ticker)
    enriched["daily_metrics"] = get_daily_metrics(ticker)
    enriched["rvol"] = compute_rvol(gapper.get("volume"), enriched["daily_metrics"].get("avg_volume_20"))
    enriched["next_earnings_date"] = get_next_earnings_date(ticker)

    day_eligible, swing_eligible = compute_eligibility(enriched)
    enriched["day_eligible"] = day_eligible
    enriched["swing_eligible"] = swing_eligible
    return enriched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("scan started")
    generated_at = datetime.now(ET).isoformat()

    market_snapshot = get_market_snapshot()

    live_movers = get_live_movers()
    if len(live_movers) >= 5:
        candidate_source = "live_screeners"
        movers = live_movers
    else:
        log(f"only {len(live_movers)} live movers found, falling back to static universe")
        candidate_source = "static_universe"
        movers = get_static_universe_movers()

    gappers_raw = filter_gappers(movers)
    log(f"{len(gappers_raw)} names passed the gap filter")

    rss_articles = fetch_rss_news()
    log(f"{len(rss_articles)} rss articles collected")

    econ_calendar = fetch_econ_calendar()

    gappers = []
    for g in gappers_raw:
        try:
            gappers.append(enrich_gapper(g, rss_articles))
        except Exception as e:
            log(f"enrichment failed for {g.get('ticker')}: {e}")
            g["enrichment_error"] = str(e)
            gappers.append(g)

    packet = {
        "generated_at": generated_at,
        "candidate_source": candidate_source,
        "trading_day_note": (
            "Raw data only, all timestamps ET. No conviction, buckets, or opinions are "
            "computed here, that judgment happens later in the AI prompts that read this file."
        ),
        "scan_params": {
            "gap_filter_min_abs_gap_pct": GAP_FILTER_MIN_ABS_GAP_PCT,
            "gap_filter_min_price": GAP_FILTER_MIN_PRICE,
            "gap_filter_top_n": GAP_FILTER_TOP_N,
            "day_trading_rules": DAY_RULES,
            "swing_rules": SWING_RULES,
        },
        "criteria": {
            "day_trading": (
                "Trend Join Long. Gap up over 3%, price over $3, market cap over $1B, "
                "premarket RVOL over 1.5, price breaking above yesterday's high. Backtest is "
                "54.6% win rate, 1.59 profit factor, 280 trades."
            ),
            "swing": (
                "Gap up 8% or more, price over $3, open above yesterday's high, open above "
                "the 200 day SMA, market cap over $800M, and a real catalyst (earnings or "
                "news). Backtest is 57.6% win rate / 5.34 profit factor on news catalysts, "
                "44.7% / 2.57 on earnings catalysts. Entry and exit management is still being "
                "built, these are starter ideas only, no stops or targets attached."
            ),
        },
        "market_snapshot": market_snapshot,
        "econ_calendar": econ_calendar,
        "gappers": gappers,
        "market_news": rss_articles[:20],
        "gaps_to_fill": [
            "Earnings info is only the next earnings date per gapper, not a full market wide earnings calendar.",
            "Intraday levels (VWAP, HOD, LOD, premarket high) come from Yahoo's 5-min bars, which can lag or gap during fast premarket moves.",
            "Premarket RVOL is a stand-in using full-day relative volume, since yfinance reports close to 0 premarket volume through this keyless path. A true premarket RVOL needs a premarket feed like Alpaca.",
        ],
    }

    with open(PACKET_PATH, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)
    log(f"packet written to {PACKET_PATH}")


if __name__ == "__main__":
    main()
