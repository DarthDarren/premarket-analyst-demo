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

import daily_structure
import watchlist_universe
from screens import ALERT, GAPPERS, WATCHLIST, load_screens

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

SCREENS = load_screens()
GAPPER_SCREENS = [s for s in SCREENS if s.universe == GAPPERS]
WATCHLIST_SCREENS = [s for s in SCREENS if s.universe == WATCHLIST]
REGIME_SYMBOLS = ["SPY", "QQQ"]
DAILY_BARS_PERIOD = "2y"
DAILY_BARS_BATCH = 100
TIER_RANK = {"core_candidate": 0, "core_owned": 1, "broad_candidate": 2}

# Gann's money-management rules (Trading Methods of W.D. Gann, ch. 6), shown with the
# portfolio alerts as reminders. Cost basis isn't in the Screener list, so they can't
# be checked per position yet.
GANN_RISK_RULES = [
    "Risk no more than about 2% of the account on any one trade.",
    "Always use a stop loss order.",
    "Once a trade shows a profit equal to the initial risk, move the stop to breakeven.",
    "Never average a loss, don't add to a position that's going against you.",
]


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
    # One boolean per screen, keyed by the screen's flag name (day_eligible, swing_eligible, ...).
    return {screen.flag: screen.passes(gapper) for screen in GAPPER_SCREENS}


def build_extra_screens(gappers):
    # Screens beyond the built-in Day and Swing get their own block, so the prompts can
    # pick them up generically. With only the built-ins loaded this is empty and the
    # packet stays exactly as it was before screens became plug-ins.
    extra = {}
    for screen in GAPPER_SCREENS:
        if screen.builtin:
            continue
        hits = []
        near_misses = []
        for g in gappers:
            failed = screen.failed_rules(g)
            if not failed:
                hits.append(g["ticker"])
            elif len(failed) == 1:
                near_misses.append({"ticker": g["ticker"], "missed": failed[0]})
        extra[screen.id] = {
            "name": screen.name,
            "status": screen.status,
            "flag": screen.flag,
            "criteria": screen.criteria,
            "plan": screen.plan,
            "hits": hits,
            "near_misses": near_misses,
        }
    return extra


# ---------------------------------------------------------------------------
# Watchlist screens: chart setups on the Screener watchlist, daily bars only
# ---------------------------------------------------------------------------

def get_daily_structures(tickers):
    """Finished daily bars for many tickers in a few batched downloads, as daily_structure.Structure."""
    today = datetime.now(ET).date()
    structures = {}
    for start in range(0, len(tickers), DAILY_BARS_BATCH):
        batch = tickers[start:start + DAILY_BARS_BATCH]
        try:
            data = yf.download(batch, period=DAILY_BARS_PERIOD, interval="1d", group_by="ticker",
                               auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            log(f"daily bars batch failed ({batch[0]}..{batch[-1]}): {e}")
            continue
        for ticker in batch:
            try:
                df = data[ticker]
                df = df.dropna(subset=["Close"])
                if len(df) and df.index[-1].date() >= today:
                    df = df.iloc[:-1]  # today's partial bar is not a finished day yet
                if len(df) >= 60:
                    structures[ticker] = daily_structure.from_dataframe(df)
            except Exception as e:
                log(f"daily structure failed for {ticker}: {e}")
    return structures


def get_market_regime(structures):
    regime = {sym: daily_structure.regime(structures.get(sym)) for sym in REGIME_SYMBOLS}
    regime["state"] = regime["SPY"]["state"]
    regime["rule"] = (
        "uptrend: close > 50-day SMA > 200-day SMA with Choppiness(14) under "
        f"{daily_structure.CHOP_TRENDING_MAX}; downtrend: the mirror image; otherwise choppy. "
        "Watchlist buy screens only fire when SPY is in an uptrend."
    )
    return regime


def hit_rank(item):
    return (TIER_RANK.get(item["tier"], 9), -len(item["source_lists"]), item["ticker"])


def build_watchlist_screens(rows, structures, regime_state):
    extra = {}
    items = []
    for row in rows:
        s = structures.get(row["ticker"])
        if s is not None:
            items.append({**row, "structure": s, "market_regime": regime_state})
    for screen in WATCHLIST_SCREENS:
        scanned = [it for it in items if not screen.tiers or it["tier"] in screen.tiers]
        hits, near = [], []
        for it in scanned:
            failed = screen.failed_rules(it)
            if not failed:
                hits.append(it)
            elif len(failed) == 1:
                near.append((it, failed[0]))
        hits.sort(key=hit_rank)
        near.sort(key=lambda x: hit_rank(x[0]))
        def note_for(it):
            try:
                return screen.describe(it) if screen.describe else ""
            except Exception:
                return ""

        details = {}
        for it in hits[:screen.max_hits]:
            details[it["ticker"]] = {"tier": it["tier"], "lists": it["source_lists"], "note": note_for(it),
                                     "chart": it["structure"].summary()}
        extra[screen.id] = {
            "name": screen.name,
            "status": screen.status,
            "universe": WATCHLIST,
            "kind": screen.kind,
            "criteria": screen.criteria,
            "plan": screen.plan,
            "scanned": len(scanned),
            "hit_count": len(hits),
            "hits": [it["ticker"] for it in hits[:screen.max_hits]],
            "hit_details": details,
            # Alerts on owned stocks carry a note for near misses too, so the report can show
            # holdings that are still in a broken trend from an earlier day.
            "near_misses": [{"ticker": it["ticker"], "missed": m, **({"note": note_for(it)} if screen.kind == ALERT else {})}
                            for it, m in near[:screen.max_hits]],
        }
    return extra


def run_watchlist_screens():
    """Returns (market_regime, watchlist_universe info, watchlist screen blocks)."""
    rows, info = watchlist_universe.load(log)
    log(f"watchlist universe: {info.get('tickers', 0)} tickers from {info.get('loaded_from')}")
    tickers = REGIME_SYMBOLS + [r["ticker"] for r in rows
                                if any(not s.tiers or r["tier"] in s.tiers for s in WATCHLIST_SCREENS)]
    structures = get_daily_structures(list(dict.fromkeys(tickers)))
    info["with_daily_bars"] = len([r for r in rows if r["ticker"] in structures])
    regime = get_market_regime(structures)
    log(f"market regime: SPY {regime['SPY']['state']}, QQQ {regime['QQQ']['state']}")
    return regime, info, build_watchlist_screens(rows, structures, regime["state"])


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

    enriched.update(compute_eligibility(enriched))
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
            **{screen.rules_key: screen.params for screen in SCREENS},
        },
        "criteria": {screen.id: screen.criteria for screen in SCREENS},
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

    extra_screens = build_extra_screens(gappers)
    if WATCHLIST_SCREENS:
        try:
            regime, universe_info, watchlist_blocks = run_watchlist_screens()
            packet["market_regime"] = regime
            packet["watchlist_universe"] = universe_info
            extra_screens.update(watchlist_blocks)
            if any(s.kind == ALERT for s in WATCHLIST_SCREENS):
                packet["portfolio_risk_rules"] = GANN_RISK_RULES
            if universe_info.get("loaded_from") != "csv" or universe_info.get("stale"):
                packet["gaps_to_fill"].append(
                    f"Watchlist screens used {universe_info.get('loaded_from')} data "
                    f"({universe_info.get('source_file') or 'no list'}, {universe_info.get('list_age_days', '?')} days old). "
                    "Re-run Screener's merge_watchlists.py to refresh the lists."
                )
        except Exception as e:
            log(f"watchlist screens failed: {e}")
            packet["gaps_to_fill"].append(f"Watchlist screens did not run today: {e}")
    if extra_screens:
        packet["extra_screens"] = extra_screens

    with open(PACKET_PATH, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)
    log(f"packet written to {PACKET_PATH}")


if __name__ == "__main__":
    main()
