#!/usr/bin/env python
"""
backtest.py - replay the watchlist buy screens over past daily bars and score every signal.

Walk-forward: on each past day the screens see only the bars up to that day's close, the
same view the premarket report gets. A signal is the first day a ticker is listed by a
screen. The trade enters at the next day's open and exits at the setup's own stop, its
target, or the close after HOLD_DAYS, whichever comes first.

Each screen is compared against a baseline: buying every watchlist stock on every day SPY
was in an uptrend (the same market filter the screens use), held the same way with no stop.

No AI calls, just Yahoo daily bars, cached in .backtest_cache/ so reruns are quick.

    python backtest.py                 # 3 years, watchlist from the newest Screener CSV
    python backtest.py --years 5
    python backtest.py --refresh       # download fresh bars instead of using the cache
    python backtest.py --tickers NVDA,MSFT,AAPL
    python backtest.py --no-variants   # only the live screens, without the backtest-only variants

Results: printed, and written to backtest_results/backtest_<date>.md plus a CSV of every signal.
"""

import argparse
import bisect
import csv
import os
import pickle
import statistics
import sys
from datetime import date, timedelta

import backtest_variants
import daily_structure
import watchlist_universe
from daily_structure import Structure, choppiness
from screens import load_screens
from screens.base import SETUP, WATCHLIST

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".backtest_cache")
RESULTS_DIR = os.path.join(HERE, "backtest_results")

HOLD_DAYS = 60                 # time exit, in trading days after entry; the setups themselves don't expire
FORWARD_DAYS = (5, 10, 20)     # plain forward returns reported alongside the trade result
VIEW_BARS = 300                # bars each day's view keeps, enough for the 200-day SMA and 120-day lookbacks
WARMUP_BARS = 250              # first bars of history used only to warm up SMAs and RSI
DOWNLOAD_BATCH = 100

# Promotion bar from the plan Darren agreed to, tightened after the first real run.
PROMOTE_MIN_SIGNALS = 30
YEAR_MIN_SIGNALS = 10          # a year counts toward "positive in most years" with this many trades


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def download(tickers, years, refresh=False):
    """{ticker: DataFrame} of daily bars, from the cache when it already covers these tickers."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"bars_{years}y.pkl")
    cached = {}
    if os.path.exists(path) and not refresh:
        with open(path, "rb") as f:
            cached = pickle.load(f)
        if cached.get("as_of") == date.today().isoformat():
            missing = [t for t in tickers if t not in cached["bars"]]
            if not missing:
                log(f"using cached bars from {path}")
                return cached["bars"]
    import yfinance as yf
    start = date.today() - timedelta(days=int(years * 365.25) + int(WARMUP_BARS * 1.5))
    bars = {}
    for i in range(0, len(tickers), DOWNLOAD_BATCH):
        batch = tickers[i:i + DOWNLOAD_BATCH]
        log(f"downloading {i + 1}-{i + len(batch)} of {len(tickers)}")
        data = yf.download(batch, start=start.isoformat(), interval="1d", group_by="ticker",
                           auto_adjust=True, threads=True, progress=False)
        for t in batch:
            try:
                df = data[t].dropna(subset=["Open", "High", "Low", "Close"])
                if len(df) and df.index[-1].date() >= date.today():
                    df = df.iloc[:-1]  # today's partial bar
                if len(df) > WARMUP_BARS:
                    bars[t] = df
            except Exception as e:
                log(f"  no bars for {t}: {e}")
    with open(path, "wb") as f:
        pickle.dump({"as_of": date.today().isoformat(), "bars": bars}, f)
    return bars


# ---------------------------------------------------------------------------
# Walk-forward views
# ---------------------------------------------------------------------------

def _between(sorted_idx, lo, hi, offset):
    """Items of sorted_idx in [lo, hi], shifted down by offset."""
    a = bisect.bisect_left(sorted_idx, lo)
    b = bisect.bisect_right(sorted_idx, hi)
    return [i - offset for i in sorted_idx[a:b]]


def view(full, t, bars=VIEW_BARS):
    """The Structure the screens would have seen at the close of bar t.

    Same result as daily_structure.build() on the bars up to t, without recomputing RSI and
    pivots every day: RSI is causal, and a 3-bar pivot at i only needs bar i + 1, so the
    full-history values cut at t are what the live scan would have had.
    """
    lo = max(0, t - bars + 1)
    sl = slice(lo, t + 1)
    s = Structure(dates=full.dates[sl], opens=full.opens[sl], highs=full.highs[sl],
                  lows=full.lows[sl], closes=full.closes[sl], volumes=full.volumes[sl])
    s.rsi = full.rsi[sl]
    s.price_pivot_lows = _between(full.price_pivot_lows, lo + 1, t - 1, lo)
    s.price_pivot_highs = _between(full.price_pivot_highs, lo + 1, t - 1, lo)
    s.rsi_troughs = _between(full.rsi_troughs, lo + 1, t - 1, lo)
    s.rsi_peaks = _between(full.rsi_peaks, lo + 1, t - 1, lo)
    c = s.closes
    s.sma_50 = sum(c[-50:]) / 50 if len(c) >= 50 else None
    s.sma_200 = sum(c[-200:]) / 200 if len(c) >= 200 else None
    if len(s.volumes) >= 21:
        avg = sum(s.volumes[-21:-1]) / 20
        s.rvol = s.volumes[-1] / avg if avg else None
    s.chop = choppiness(s.highs[-20:], s.lows[-20:], c[-20:])
    return s


def regime_by_date(spy):
    out = {}
    for t in range(WARMUP_BARS, len(spy.closes)):
        out[spy.dates[t]] = daily_structure.regime(view(spy, t))["state"]
    return out


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def _walk(full, e, entry, stop, target, on_close):
    """(exit price, reason, days held). on_close: the stop only counts on a close beyond it, the way
    the screens drop a setup; otherwise any trade through it (wick or gap) stops the trade."""
    for j in range(e, e + HOLD_DAYS):
        if target is not None and full.highs[j] >= target and (on_close or full.lows[j] > stop or stop is None):
            # With a close-based stop the target, touched during the day, comes first. With a wick stop
            # and both inside one daily bar the order is unknown, so the stop is assumed first.
            return max(target, full.opens[j]), "target", j - e + 1
        if stop is not None:
            if on_close and full.closes[j] < stop:
                return full.closes[j], "stop", j - e + 1
            if not on_close and j > e and full.opens[j] <= stop:
                return full.opens[j], "stop (gap)", j - e + 1
            if not on_close and full.lows[j] <= stop:
                return stop, "stop", j - e + 1
    return full.closes[e + HOLD_DAYS - 1], "time", HOLD_DAYS


def simulate(full, t, stop, target, entry=None):
    """Trade a signal listed at the close of bar t. Returns None when there aren't HOLD_DAYS bars after it yet.

    entry, when given, is the setup's own buy limit at bar t's close (the sheets buy the close of
    the candle that completes the setup). Otherwise, or when the setup is first listed on a later
    day, the trade enters at the next open.

    The main result exits on a close below the stop, matching the screens' own "no close below"
    rules. return_wick_pct is the same trade with an intraday stop, as a sensitivity check.
    """
    e = t + 1
    if e + HOLD_DAYS - 1 > full.last:
        return None
    entry = entry if entry is not None else full.opens[e]
    if not entry or (stop is not None and entry <= stop):
        return {"skipped": "entry at or below the stop", "exit_index": e}
    if target is not None and entry >= target:
        return {"skipped": "entry at or above the target", "exit_index": e}
    exit_px, why, days = _walk(full, e, entry, stop, target, on_close=True)
    wick_px, _, _ = _walk(full, e, entry, stop, target, on_close=False)
    risk = entry - stop if stop is not None else None
    out = {
        "entry": entry, "stop": stop, "target": target, "exit": exit_px, "exit_reason": why, "days": days,
        "exit_index": e + days - 1,
        "return_pct": 100.0 * (exit_px - entry) / entry,
        "return_wick_pct": 100.0 * (wick_px - entry) / entry,
        "r_multiple": (exit_px - entry) / risk if risk else None,
    }
    for n in FORWARD_DAYS:
        out[f"fwd_{n}d_pct"] = 100.0 * (full.closes[e + n - 1] - entry) / entry
    return out


def forward_returns(full, t):
    e = t + 1
    if e + max(FORWARD_DAYS) - 1 > full.last or not full.opens[e]:
        return None
    entry = full.opens[e]
    return {n: 100.0 * (full.closes[e + n - 1] - entry) / entry for n in FORWARD_DAYS}


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay(rows, structures, regimes, screens, start_date):
    """Returns (signals, baseline) where baseline is {n: [forward returns]} for SPY-uptrend days."""
    signals = []
    baseline = {n: [] for n in FORWARD_DAYS}
    for k, row in enumerate(rows, 1):
        full = structures.get(row["ticker"])
        if full is None:
            continue
        mine = [sc for sc in screens if not sc.tiers or row["tier"] in sc.tiers]
        # One trade per setup: a setup is identified by its own pivots, so a day off the list (an SPY
        # blip) doesn't re-enter it, and nothing new opens while a trade on this screen is still held.
        traded = {sc.id: set() for sc in mine}
        busy_until = {sc.id: -1 for sc in mine}
        first = max(WARMUP_BARS, bisect.bisect_left(full.dates, start_date))
        for t in range(first, full.last):
            state = regimes.get(full.dates[t], "unknown")
            if state == "uptrend":
                fwd = forward_returns(full, t)
                if fwd:
                    for n in FORWARD_DAYS:
                        baseline[n].append(fwd[n])
            item = {**row, "structure": view(full, t), "market_regime": state}
            for sc in mine:
                if t <= busy_until[sc.id] or not sc.passes(item):
                    continue
                plan = sc.trade(item)
                if plan["key"] in traded[sc.id]:
                    continue
                traded[sc.id].add(plan["key"])
                sig = signal(sc, row, full, t, item, plan)
                busy_until[sc.id] = sig.get("exit_index", full.last)
                signals.append(sig)
        if k % 25 == 0:
            log(f"  replayed {k} of {len(rows)} tickers, {len(signals)} signals so far")
    return signals, baseline


def signal(sc, row, full, t, item, plan):
    note = ""
    try:
        note = sc.describe(item) if sc.describe else ""
    except Exception:
        pass
    sig = {"screen": sc.id, "ticker": row["ticker"], "tier": row["tier"], "date": str(full.dates[t]),
           "new": note.startswith("NEW"), "plan": plan["plan"], "note": note}
    # The setup's own entry applies only when it is listed on the bar that completes it.
    entry = plan.get("entry") if plan.get("entry_date") == str(full.dates[t]) else None
    trade = simulate(full, t, plan["stop"], plan["target"], entry)
    sig.update(trade or {"skipped": "not enough bars after it yet"})
    return sig


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def mean(xs):
    return statistics.fmean(xs) if xs else None


def score(signals, baseline, screens):
    base = {n: mean(baseline[n]) for n in FORWARD_DAYS}
    rows = []
    for sc in screens:
        mine = [s for s in signals if s["screen"] == sc.id]
        done = [s for s in mine if "return_pct" in s]
        rets = [s["return_pct"] for s in done]
        rs = [s["r_multiple"] for s in done if s["r_multiple"] is not None]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        exp = mean(rets)
        days = sum(s["days"] for s in done)
        # Return per day in the trade, compared with simply holding a watchlist stock for 20 days.
        per_day = sum(rets) / days if days else None
        base_per_day = base[20] / 20 if base[20] is not None else None
        years = by_year(done)
        counted = [e for n, e in years.values() if n >= YEAR_MIN_SIGNALS]
        good_years = sum(1 for e in counted if e > 0)
        verdict = "not enough signals"
        if len(done) >= PROMOTE_MIN_SIGNALS:
            beats = per_day is not None and base_per_day is not None and per_day > base_per_day
            steady = bool(counted) and good_years * 3 >= len(counted) * 2
            verdict = "promote" if exp > 0 and beats and steady else "keep in Lab"
        rows.append({
            "screen": sc.name, "id": sc.id,
            "signals": len(done),
            "skipped": len(mine) - len(done),
            "win_rate": 100.0 * len(wins) / len(done) if done else None,
            "avg_win": mean(wins), "avg_loss": mean(losses),
            "expectancy": exp, "median_r": statistics.median(rs) if rs else None,
            "expectancy_wick": mean([s["return_wick_pct"] for s in done]),
            "stop_rate": 100.0 * sum(s["exit_reason"].startswith("stop") for s in done) / len(done) if done else None,
            "target_rate": 100.0 * sum(s["exit_reason"] == "target" for s in done) / len(done) if done else None,
            **{f"fwd_{n}": mean([s[f"fwd_{n}d_pct"] for s in done]) for n in FORWARD_DAYS},
            "plan": done[0]["plan"] if done else "",
            "avg_days": days / len(done) if done else None,
            "per_day": per_day,
            "good_years": f"{good_years}/{len(counted)}",
            "verdict": verdict,
            "by_year": years,
        })
    return rows, base


def by_year(done):
    years = {}
    for s in done:
        years.setdefault(s["date"][:4], []).append(s["return_pct"])
    return {y: (len(v), mean(v)) for y, v in sorted(years.items())}


def fmt(x, d=1, pct=False):
    if x is None:
        return "-"
    return f"{x:+.{d}f}%" if pct else f"{x:.{d}f}"


def report(rows, base, info):
    lines = [
        f"# Screen backtest, {info['start']} to {info['end']}",
        "",
        f"{info['tickers']} watchlist tickers, {info['baseline_days']:,} stock-days with SPY in an uptrend as the baseline. "
        "Entry at the setup's own buy limit (the close of the bar that completes it) when it is listed that day, "
        "otherwise at the next day's open. Exit on a close below the setup's stop (the same level the screen drops it on), "
        f"at its target, or at the close {HOLD_DAYS} trading days later. One trade per setup, and none opens on a screen "
        "while an earlier trade on that ticker is still held. "
        "Returns are per trade, before commissions and slippage.",
        "",
        "| Screen | Signals | Win rate | Avg win | Avg loss | Expectancy | Avg days | Per day held | Good years | Median R | Stopped | Target hit | 20-day fwd | Expectancy, wick stops | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['screen']} | {r['signals']} | {fmt(r['win_rate'], 0)}% | {fmt(r['avg_win'], pct=True)} | "
            f"{fmt(r['avg_loss'], pct=True)} | {fmt(r['expectancy'], 2, pct=True)} | {fmt(r['avg_days'], 0)} | "
            f"{fmt(r['per_day'], 3, pct=True)} | {r['good_years']} | {fmt(r['median_r'], 2)} | "
            f"{fmt(r['stop_rate'], 0)}% | {fmt(r['target_rate'], 0)}% | {fmt(r['fwd_20'], 2, pct=True)} | "
            f"{fmt(r['expectancy_wick'], 2, pct=True)} | **{r['verdict']}** |"
        )
    lines += [
        "",
        f"Baseline (any watchlist stock, any SPY-uptrend day): 5-day {fmt(base[5], 2, pct=True)}, "
        f"10-day {fmt(base[10], 2, pct=True)}, 20-day {fmt(base[20], 2, pct=True)}.",
        "",
        f"Baseline per day held: {fmt(base[20] / 20 if base[20] is not None else None, 3, pct=True)} "
        "(the 20-day baseline spread over 20 days).",
        "",
        f"Promote means {PROMOTE_MIN_SIGNALS}+ signals, positive expectancy, a return per day held above the baseline's, "
        f"and positive expectancy in at least two thirds of the years with {YEAR_MIN_SIGNALS}+ trades.",
        "",
        "Rows marked [variant] are backtest-only tweaks (backtest_variants.py); the live screens follow their "
        "source material. A variant's \"promote\" means the tweak is worth adopting, not that it is live.",
        "",
        "## By year (signals, expectancy)",
        "",
    ]
    years = sorted({y for r in rows for y in r["by_year"]})
    lines.append("| Screen | " + " | ".join(years) + " |")
    lines.append("|---|" + "---|" * len(years))
    for r in rows:
        cells = []
        for y in years:
            n, e = r["by_year"].get(y, (0, None))
            cells.append(f"{n}, {fmt(e, 2, pct=True)}" if n else "-")
        lines.append(f"| {r['screen']} | " + " | ".join(cells) + " |")
    lines += ["", "## Exits used", ""]
    lines += [f"- {r['screen']}: {r['plan'] or '-'}" for r in rows]
    lines += [
        "",
        "## Caveats",
        "",
        "- The universe is today's watchlist, so stocks that dropped off it after doing badly are missing. "
        "That flatters every screen and the baseline alike.",
        "- R is the result over the distance from entry to the stop. When the entry sits just above the stop "
        "that distance is tiny and one gap gives a huge R, so the median is shown instead of the average.",
        "- The wick-stops column is the same trades stopped on any trade through the stop instead of a close. "
        "With daily bars, when that stop and the target fall on the same day, the stop is assumed to hit first.",
        f"- Signals in the last {HOLD_DAYS} trading days have no result yet and are left out.",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--refresh", action="store_true", help="download fresh bars instead of using today's cache")
    ap.add_argument("--tickers", help="comma-separated tickers instead of the watchlist")
    ap.add_argument("--no-variants", action="store_true", help="skip the backtest-only variants in backtest_variants.py")
    args = ap.parse_args(argv)

    screens = [sc for sc in load_screens() if sc.universe == WATCHLIST and sc.kind == SETUP]
    for sc in [sc for sc in screens if sc.trade is None]:
        log(f"skipping {sc.id}: it has no trade() with a stop and target, so it can't be scored")
    screens = [sc for sc in screens if sc.trade is not None]
    if not args.no_variants:
        screens += backtest_variants.variants(screens)
    if args.tickers:
        rows = [{"ticker": t.strip().upper(), "tier": "core_candidate", "source_lists": [], "owned": False}
                for t in args.tickers.split(",") if t.strip()]
    else:
        rows, _ = watchlist_universe.load(log)
        tiers = {t for sc in screens for t in sc.tiers}
        rows = [r for r in rows if not tiers or r["tier"] in tiers]
    if not rows:
        log("no tickers to test")
        return 1

    tickers = list(dict.fromkeys(["SPY"] + [r["ticker"] for r in rows]))
    bars = download(tickers, args.years, args.refresh)
    if "SPY" not in bars:
        log("no SPY bars, can't tell the market trend")
        return 1
    structures = {t: daily_structure.from_dataframe(df) for t, df in bars.items()}
    regimes = regime_by_date(structures["SPY"])
    start_date = structures["SPY"].dates[-1] - timedelta(days=int(args.years * 365.25))

    log(f"replaying {len(screens)} screens on {len(rows)} tickers from {start_date}")
    signals, baseline = replay(rows, structures, regimes, screens, start_date)
    rows_out, base = score(signals, baseline, screens)
    info = {"start": start_date, "end": structures["SPY"].dates[-1],
            "tickers": sum(1 for r in rows if r["ticker"] in structures), "baseline_days": len(baseline[20])}
    md = report(rows_out, base, info)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    md_path = os.path.join(RESULTS_DIR, f"backtest_{stamp}.md")
    csv_path = os.path.join(RESULTS_DIR, f"backtest_signals_{stamp}.csv")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    fields = ["screen", "ticker", "tier", "date", "new", "entry", "stop", "target", "exit", "exit_reason", "days",
              "return_pct", "r_multiple"] + [f"fwd_{n}d_pct" for n in FORWARD_DAYS] + ["skipped", "note"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(signals)
    print()
    print(md)
    log(f"\nwrote {md_path}\nwrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
