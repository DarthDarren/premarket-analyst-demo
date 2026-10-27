#!/usr/bin/env python
"""
backtest_ema.py - test the 9-day EMA trend rule on the watchlist, outside the report.

The rule: buy when a stock closes above its 9-day EMA, sell when it closes below it. Both
orders fill at the next day's open, the earliest a trader reading the premarket report could
act on the close. Each variant below changes one thing, so its effect can be read off the table:

    ema9          the plain rule
    ema9_spy      only buys while SPY is in an uptrend (the screens' market filter)
    ema9_trend    only buys when the stock is above its 50-day SMA and the 50-day is above the 200-day
    ema9_2closes  sells only after two closes in a row below the 9-day EMA
    ema9_21       only buys while the 9-day EMA is above the 21-day EMA
    ema21         the plain rule on the 21-day EMA, for comparison

Every rule is scored against the same baseline as backtest.py: holding any watchlist stock on
any SPY-uptrend day, per day held. Short trades pay commissions and slippage often, so results
are shown before and after a round-trip cost (--cost, default 0.10%).

Reuses backtest.py's bar cache, so a run right after backtest.py downloads nothing.

    python backtest_ema.py
    python backtest_ema.py --years 5 --cost 0.2
    python backtest_ema.py --tickers NVDA,MSFT,AAPL

Results: printed, and written to backtest_results/backtest_ema_<date>.md plus a CSV of every trade.
"""

import argparse
import csv
import os
import sys
from datetime import date, timedelta

import backtest
import daily_structure
import watchlist_universe
from backtest import fmt, log, mean

DEFAULT_COST_PCT = 0.10        # round trip, commissions plus slippage
BASE_DAYS = 20                 # baseline holding period, the same one backtest.py uses


def ema(closes, n):
    """n-day EMA, seeded with the SMA of the first n closes; None before that."""
    out = [None] * len(closes)
    if len(closes) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    out[n - 1] = e
    for i in range(n, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def sma(closes, n):
    out = [None] * len(closes)
    run = 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= n:
            run -= closes[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


class Rule:
    def __init__(self, id, name, fast=9, exit_closes=1, spy=False, trend=False, slow=None):
        self.id, self.name = id, name
        self.fast, self.exit_closes, self.spy, self.trend, self.slow = fast, exit_closes, spy, trend, slow


RULES = [
    Rule("ema9", "Close above / below the 9-day EMA"),
    Rule("ema9_spy", "9-day EMA, buys only with SPY in an uptrend", spy=True),
    Rule("ema9_trend", "9-day EMA, buys only above a rising 50/200-day SMA", trend=True),
    Rule("ema9_2closes", "9-day EMA, sells after two closes below", exit_closes=2),
    Rule("ema9_21", "9-day EMA, buys only with the 9-day above the 21-day", slow=21),
    Rule("ema21", "Close above / below the 21-day EMA", fast=21),
]


def indicators(full):
    c = full.closes
    return {"ema9": ema(c, 9), "ema21": ema(c, 21), "sma50": sma(c, 50), "sma200": sma(c, 200)}


def trades(rule, full, ind, regimes, first):
    """Every completed trade of rule on one stock, with entries on signals from bar index first onward.

    A buy signal is a close above the EMA after a close at or below it, so a stock already above
    its EMA on the first day waits for a fresh cross instead of being bought mid-run.
    """
    c, line = full.closes, ind[f"ema{rule.fast}"]
    slow = ind[f"ema{rule.slow}"] if rule.slow else None
    out, held, below = [], None, 0
    for t in range(max(first, 1), full.last):        # the fill is at t + 1's open, so t stops one short
        if line[t] is None or line[t - 1] is None:
            continue
        if held is None:
            crossed = c[t] > line[t] and c[t - 1] <= line[t - 1]
            if not crossed:
                continue
            if rule.spy and regimes.get(full.dates[t]) != "uptrend":
                continue
            if rule.trend and not (ind["sma200"][t] is not None and c[t] > ind["sma50"][t] > ind["sma200"][t]):
                continue
            if slow is not None and not (slow[t] is not None and line[t] > slow[t]):
                continue
            held, below = t + 1, 0
            continue
        below = below + 1 if c[t] < line[t] else 0
        if below >= rule.exit_closes:
            e, x = held, t + 1
            entry, exit_px = full.opens[e], full.opens[x]
            if entry:
                out.append({"date": full.dates[e].isoformat(), "entry": entry, "exit": exit_px,
                            "exit_date": full.dates[x].isoformat(), "days": x - e,
                            "return_pct": 100.0 * (exit_px - entry) / entry})
            held = None
    return out                                         # a trade still open on the last bar is left out


def baseline(structures, tickers, regimes, start_date):
    """Forward BASE_DAYS returns from the next open, for every stock on every SPY-uptrend day."""
    rets = []
    for tk in tickers:
        full = structures.get(tk)
        if full is None:
            continue
        for t in range(len(full.closes)):
            e = t + 1
            if full.dates[t] < start_date or e + BASE_DAYS - 1 > full.last or not full.opens[e]:
                continue
            if regimes.get(full.dates[t]) == "uptrend":
                rets.append(100.0 * (full.closes[e + BASE_DAYS - 1] - full.opens[e]) / full.opens[e])
    return mean(rets), len(rets)


def score(rule, done, cost, base_per_day, market_days):
    rets = [d["return_pct"] for d in done]
    net = [r - cost for r in rets]
    days = sum(d["days"] for d in done)
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    years = {}
    for d, r in zip(done, net):
        years.setdefault(d["date"][:4], []).append(r)
    years = {y: (len(v), mean(v)) for y, v in sorted(years.items())}
    counted = [e for n, e in years.values() if n >= backtest.YEAR_MIN_SIGNALS]
    good = sum(1 for e in counted if e > 0)
    per_day = sum(rets) / days if days else None
    per_day_net = sum(net) / days if days else None
    verdict = "not enough trades"
    if len(done) >= backtest.PROMOTE_MIN_SIGNALS:
        beats = per_day_net is not None and base_per_day is not None and per_day_net > base_per_day
        steady = bool(counted) and good * 3 >= len(counted) * 2
        verdict = "beats holding" if mean(net) > 0 and beats and steady else "doesn't beat holding"
    return {
        "rule": rule.name, "id": rule.id, "trades": len(done),
        "win_rate": 100.0 * len(wins) / len(done) if done else None,
        "avg_win": mean(wins), "avg_loss": mean(losses),
        "expectancy": mean(rets), "expectancy_net": mean(net),
        "avg_days": days / len(done) if done else None,
        "in_market": 100.0 * days / market_days if market_days else None,
        "per_day": per_day, "per_day_net": per_day_net,
        "good_years": f"{good}/{len(counted)}", "by_year": years, "verdict": verdict,
    }


def report(rows, info):
    base = info["base_per_day"]
    lines = [
        f"# 9-day EMA backtest, {info['start']} to {info['end']}",
        "",
        f"{info['tickers']} watchlist tickers. Buy at the next open after a close above the EMA, sell at the next "
        "open after a close below it. Returns are per trade; \"net\" takes off a "
        f"{info['cost']:.2f}% round-trip cost. In market is the share of stock-days a trade was held.",
        "",
        "| Rule | Trades | Win rate (net) | Avg win | Avg loss | Expectancy | Expectancy, net | Avg days | In market | "
        "Per day held | Per day, net | Good years | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['rule']} | {r['trades']} | {fmt(r['win_rate'], 0)}% | {fmt(r['avg_win'], pct=True)} | "
            f"{fmt(r['avg_loss'], pct=True)} | {fmt(r['expectancy'], 2, pct=True)} | "
            f"{fmt(r['expectancy_net'], 2, pct=True)} | {fmt(r['avg_days'], 1)} | {fmt(r['in_market'], 0)}% | "
            f"{fmt(r['per_day'], 3, pct=True)} | {fmt(r['per_day_net'], 3, pct=True)} | {r['good_years']} | "
            f"**{r['verdict']}** |"
        )
    lines += [
        "",
        f"Baseline per day held: {fmt(base, 3, pct=True)} (any watchlist stock bought on any SPY-uptrend day and "
        f"held {BASE_DAYS} days, from {info['baseline_days']:,} stock-days; the same baseline as backtest.py).",
        "",
        f"\"Beats holding\" means {backtest.PROMOTE_MIN_SIGNALS}+ trades, positive net expectancy, a net return per "
        "day held above the baseline's, and positive net expectancy in at least two thirds of the years with "
        f"{backtest.YEAR_MIN_SIGNALS}+ trades.",
        "",
        "## By year (trades, net expectancy)",
        "",
    ]
    years = sorted({y for r in rows for y in r["by_year"]})
    lines.append("| Rule | " + " | ".join(years) + " |")
    lines.append("|---|" + "---|" * len(years))
    for r in rows:
        cells = []
        for y in years:
            n, e = r["by_year"].get(y, (0, None))
            cells.append(f"{n}, {fmt(e, 2, pct=True)}" if n else "-")
        lines.append(f"| {r['rule']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Caveats",
        "",
        "- The universe is today's watchlist, so stocks that dropped off it after doing badly are missing.",
        "- Per day held only counts days in a trade. A rule that is in the market a small share of the time can "
        "beat the baseline per day and still make less in total than holding.",
        "- Fills are at the next open, so overnight gaps against the position are included.",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--refresh", action="store_true", help="download fresh bars instead of using today's cache")
    ap.add_argument("--tickers", help="comma-separated tickers instead of the watchlist")
    ap.add_argument("--cost", type=float, default=DEFAULT_COST_PCT, help="round-trip cost in percent")
    args = ap.parse_args(argv)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        rows, _ = watchlist_universe.load(log)
        tickers = [r["ticker"] for r in rows if r["tier"] != "exclude"]
    if not tickers:
        log("no tickers to test")
        return 1

    bars = backtest.download(list(dict.fromkeys(["SPY"] + tickers)), args.years, args.refresh)
    if "SPY" not in bars:
        log("no SPY bars, can't tell the market trend")
        return 1
    structures = {t: daily_structure.from_dataframe(df) for t, df in bars.items()}
    regimes = backtest.regime_by_date(structures["SPY"])
    start_date = structures["SPY"].dates[-1] - timedelta(days=int(args.years * 365.25))
    tickers = [t for t in tickers if t in structures]

    log(f"testing {len(RULES)} rules on {len(tickers)} tickers from {start_date}")
    done = {r.id: [] for r in RULES}
    market_days = 0
    for tk in tickers:
        full = structures[tk]
        first = next((i for i, d in enumerate(full.dates) if d >= start_date), len(full.dates))
        market_days += max(0, full.last - first)
        ind = indicators(full)
        for rule in RULES:
            for tr in trades(rule, full, ind, regimes, first):
                done[rule.id].append({"rule": rule.id, "ticker": tk, **tr})

    base_20, base_n = baseline(structures, tickers, regimes, start_date)
    base_per_day = base_20 / BASE_DAYS if base_20 is not None else None
    rows_out = [score(r, done[r.id], args.cost, base_per_day, market_days) for r in RULES]
    info = {"start": start_date, "end": structures["SPY"].dates[-1], "tickers": len(tickers),
            "cost": args.cost, "base_per_day": base_per_day, "baseline_days": base_n}
    md = report(rows_out, info)

    os.makedirs(backtest.RESULTS_DIR, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    md_path = os.path.join(backtest.RESULTS_DIR, f"backtest_ema_{stamp}.md")
    csv_path = os.path.join(backtest.RESULTS_DIR, f"backtest_ema_trades_{stamp}.csv")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rule", "ticker", "date", "entry", "exit_date", "exit", "days", "return_pct"])
        w.writeheader()
        for r in RULES:
            w.writerows(done[r.id])
    print()
    print(md)
    log(f"\nwrote {md_path}\nwrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
