#!/usr/bin/env python
"""
Trend Join Long (TJL) breakout strategy backtest — Python/yfinance port.

Replicates the exact entry/exit logic from the "Demo TJL Strategy" PineScript
built earlier (TradingView), extended to the full watchlist universe over the
last 60 days. Built in Python because PineScript's request.security-based
approach and TradingView's MCP data tools are both impractical for bulk
multi-symbol historical backtesting (the MCP's 1m/5m intraday fetch is
hard-capped at ~300 bars regardless of requested count or chart position,
observed directly in this same session).

Strategy logic (unchanged from the Pine version):
  daily_breakout    = curr_px > prev_daily_high  AND  prev_daily_close > daily SMA200
  intraday_breakout = curr_px > premarket_high   AND  curr_px > today's high-so-far
                       (excluding the current bar)
  Entry: once per day, only within 10:00-15:30 ET, when both conditions hold
         and no position is already open for that symbol.
  Exit:  flatten at 15:55-16:00 ET (end-of-day flatten — same addition made in
         the Pine version, since the original scan spec only ever defined a
         point-in-time PASS/fail condition, not a full trade lifecycle).

Data: yfinance, 5-minute bars, prepost=True (premarket/after-hours included),
period="60d" for intraday, period="400d" for daily (needed for a full 200-day
SMA lookback prior to the 60-day backtest window).

Position sizing: each symbol is backtested independently against its own
$100,000 hypothetical account (100% of equity per trade, compounding across
that symbol's own sequential trades) — this exactly mirrors the Pine
strategy's `default_qty_type=strategy.percent_of_equity, default_qty_value=100`
config, just repeated per symbol rather than modeling one shared portfolio
with capital allocation across symbols (which the original spec never asked
for and would have been unrequested added complexity).

SPY/QQQ regime filter (added on top of the above): entries additionally
require regime_ok, latched once per day at the first 5-min bar at/after
10:00 ET as (SPY close > SPY's previous daily close) AND (QQQ close > QQQ's
previous daily close), held for the rest of that day. SPY/QQQ are fetched
once per run (not once per symbol) and shared across every symbol's backtest,
since it's a single market-wide signal, not something that varies per symbol.
"""

import sys
import time
import json
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

WATCHLIST = [
    "AAPL", "ADPT", "AMAT", "AMD", "AMZN", "ANET", "APH", "ARM", "ASML", "AUR",
    "AVGO", "AXON", "AXP", "BWXT", "CAT", "CCJ", "CEG", "CLS", "COHR", "COIN",
    "COPX", "CRWD", "CRWV", "DAPP", "DASH", "DELL", "DOCN", "DY", "ENVX", "ETH",
    "FIX", "FN", "FROG", "GEV", "GLW", "GOOGL", "HOOD", "HWM", "INTC", "IONQ",
    "IOT", "ISRG", "JOBY", "KLAC", "LRCX", "META", "MP", "MPC", "MPWR", "MRVL",
    "MSFT", "MU", "NASA", "NBIS", "NFLX", "NVDA", "NVMI", "OKLO", "OPEN", "OPRA",
    "ORCL", "P", "PAAS", "PALL", "PANW", "PHYS", "PLAB", "PPLT", "PSLV", "QCOM",
    "RDDT", "SMTC", "SNDK", "SNPS", "SOFI", "SPOT", "STX", "TDY", "TEM", "TER",
    "TSLA", "TSM", "URA", "VRT", "VST", "XBI", "PLTR", "RMBS", "RXRX", "SMR",
]

PREMARKET_START_MIN = 4 * 60          # 04:00 ET
MARKET_OPEN_MIN = 9 * 60 + 30         # 09:30 ET
ENTRY_WINDOW_START_MIN = 10 * 60      # 10:00 ET
ENTRY_WINDOW_END_MIN = 15 * 60 + 30   # 15:30 ET
EOD_FLATTEN_START_MIN = 15 * 60 + 55  # 15:55 ET
MARKET_CLOSE_MIN = 16 * 60            # 16:00 ET

INITIAL_CAPITAL = 100_000.0


def minutes_of_day(ts: pd.Timestamp) -> int:
    return ts.hour * 60 + ts.minute


def fetch_symbol_data(symbol: str):
    daily = yf.Ticker(symbol).history(period="400d", interval="1d", auto_adjust=False)
    intraday = yf.Ticker(symbol).history(period="60d", interval="5m", prepost=True, auto_adjust=False)
    if daily.empty or intraday.empty:
        raise ValueError(f"empty data (daily={len(daily)} rows, intraday={len(intraday)} rows)")
    return daily, intraday


def fetch_regime_data():
    """Build a per-trading-day regime_ok lookup, shared across every symbol's
    backtest (SPY/QQQ are fetched once here, not per-symbol).

    regime_ok = SPY's close at the first 5-min bar at/after 10:00 ET that day
    is above SPY's previous daily close, AND QQQ's close at that same bar is
    above QQQ's previous daily close. Latched once per day at that first
    >=10:00 ET bar and held for the rest of the day (mirrors the Pine version:
    computed once, then frozen until the next new day).
    """
    spy_daily, spy_intraday = fetch_symbol_data("SPY")
    qqq_daily, qqq_intraday = fetch_symbol_data("QQQ")

    spy_daily = spy_daily.copy()
    spy_daily["prev_close"] = spy_daily["Close"].shift(1)
    spy_prev_by_date = spy_daily.set_index(spy_daily.index.date)["prev_close"]

    qqq_daily = qqq_daily.copy()
    qqq_daily["prev_close"] = qqq_daily["Close"].shift(1)
    qqq_prev_by_date = qqq_daily.set_index(qqq_daily.index.date)["prev_close"]

    spy_intraday = spy_intraday.copy()
    spy_intraday["date"] = spy_intraday.index.date
    qqq_intraday = qqq_intraday.copy()
    qqq_intraday["date"] = qqq_intraday.index.date

    regime_by_date = {}
    all_dates = sorted(set(spy_intraday["date"]) & set(qqq_intraday["date"]))
    for d in all_dates:
        if d not in spy_prev_by_date.index or d not in qqq_prev_by_date.index:
            continue
        spy_prev_close = spy_prev_by_date.loc[d]
        qqq_prev_close = qqq_prev_by_date.loc[d]
        if pd.isna(spy_prev_close) or pd.isna(qqq_prev_close):
            continue

        spy_day = spy_intraday[spy_intraday["date"] == d].sort_index()
        qqq_day = qqq_intraday[qqq_intraday["date"] == d].sort_index()
        spy_after_10 = spy_day[spy_day.index.map(minutes_of_day) >= ENTRY_WINDOW_START_MIN]
        qqq_after_10 = qqq_day[qqq_day.index.map(minutes_of_day) >= ENTRY_WINDOW_START_MIN]
        if spy_after_10.empty or qqq_after_10.empty:
            continue

        spy_latch_close = spy_after_10.iloc[0]["Close"]
        qqq_latch_close = qqq_after_10.iloc[0]["Close"]
        regime_by_date[d] = bool(spy_latch_close > spy_prev_close and qqq_latch_close > qqq_prev_close)

    return regime_by_date


def backtest_symbol(symbol: str, daily: pd.DataFrame, intraday: pd.DataFrame, regime_by_date: dict):
    # Non-repainting daily context: shift(1) excludes today's still-forming bar.
    daily = daily.copy()
    daily["prev_daily_high"] = daily["High"].shift(1)
    daily["prev_daily_close"] = daily["Close"].shift(1)
    daily["sma200"] = daily["Close"].rolling(200).mean().shift(1)
    daily_by_date = daily.set_index(daily.index.date)

    intraday = intraday.copy()
    intraday["date"] = intraday.index.date

    trades = []
    equity = INITIAL_CAPITAL

    for trade_date, day_bars in intraday.groupby("date"):
        if trade_date not in daily_by_date.index:
            continue
        ctx = daily_by_date.loc[trade_date]
        prev_daily_high = ctx["prev_daily_high"]
        prev_daily_close = ctx["prev_daily_close"]
        sma200 = ctx["sma200"]
        if pd.isna(prev_daily_high) or pd.isna(prev_daily_close) or pd.isna(sma200):
            continue

        day_bars = day_bars.sort_index()
        pmh = None
        today_hod = None
        entered_today = False
        position_open = False
        entry_price = None
        entry_time = None

        for ts, bar in day_bars.iterrows():
            mod = minutes_of_day(ts)
            high = bar["High"]
            close = bar["Close"]

            is_premarket = PREMARKET_START_MIN <= mod < MARKET_OPEN_MIN
            is_regular = MARKET_OPEN_MIN <= mod < MARKET_CLOSE_MIN
            in_entry_window = ENTRY_WINDOW_START_MIN <= mod < ENTRY_WINDOW_END_MIN
            is_eod_flatten = EOD_FLATTEN_START_MIN <= mod < MARKET_CLOSE_MIN

            if is_premarket:
                pmh = high if pmh is None else max(pmh, high)

            if is_regular:
                curr_px = close
                daily_breakout = curr_px > prev_daily_high and prev_daily_close > sma200
                intraday_breakout = (
                    pmh is not None and today_hod is not None
                    and curr_px > pmh and curr_px > today_hod
                )

                if (
                    in_entry_window and daily_breakout and intraday_breakout
                    and not entered_today and not position_open
                    and regime_by_date.get(trade_date) is True
                ):
                    position_open = True
                    entry_price = curr_px
                    entry_time = ts
                    entered_today = True

                if is_eod_flatten and position_open:
                    exit_price = curr_px
                    shares = equity / entry_price
                    pnl = shares * (exit_price - entry_price)
                    equity += pnl
                    trades.append({
                        "symbol": symbol, "entry_time": str(entry_time), "exit_time": str(ts),
                        "entry_price": round(entry_price, 4), "exit_price": round(exit_price, 4),
                        "pnl": round(pnl, 2), "return_pct": round((exit_price / entry_price - 1) * 100, 3),
                    })
                    position_open = False

                # Update today_hod AFTER using it, so the current bar never sees its own high.
                today_hod = high if today_hod is None else max(today_hod, high)

        # Safety net: force-close anything still open at end of day (shouldn't normally
        # trigger since the EOD flatten window covers the last bars of every regular day).
        if position_open:
            exit_price = day_bars.iloc[-1]["Close"]
            shares = equity / entry_price
            pnl = shares * (exit_price - entry_price)
            equity += pnl
            trades.append({
                "symbol": symbol, "entry_time": str(entry_time), "exit_time": str(day_bars.index[-1]),
                "entry_price": round(entry_price, 4), "exit_price": round(exit_price, 4),
                "pnl": round(pnl, 2), "return_pct": round((exit_price / entry_price - 1) * 100, 3),
                "note": "forced_close_end_of_day_data",
            })

    return trades, equity


def main():
    print("Fetching SPY/QQQ regime data...", file=sys.stderr)
    regime_by_date = fetch_regime_data()
    regime_ok_days = sum(1 for v in regime_by_date.values() if v)
    regime_fail_days = sum(1 for v in regime_by_date.values() if not v)
    print(f"Regime: {regime_ok_days} OK days, {regime_fail_days} fail days "
          f"({len(regime_by_date)} total)", file=sys.stderr)

    all_trades = []
    per_symbol_summary = []
    failures = []

    for i, symbol in enumerate(WATCHLIST, 1):
        print(f"[{i}/{len(WATCHLIST)}] {symbol}...", file=sys.stderr)
        try:
            daily, intraday = fetch_symbol_data(symbol)
            trades, final_equity = backtest_symbol(symbol, daily, intraday, regime_by_date)
            all_trades.extend(trades)
            per_symbol_summary.append({
                "symbol": symbol,
                "trades": len(trades),
                "final_equity": round(final_equity, 2),
                "return_pct": round((final_equity / INITIAL_CAPITAL - 1) * 100, 3),
            })
        except Exception as e:
            failures.append({"symbol": symbol, "error": str(e)})
            print(f"  SKIPPED: {e}", file=sys.stderr)
        time.sleep(0.3)  # be polite to Yahoo's endpoint across ~180 requests

    total_trades = len(all_trades)
    winning_trades = [t for t in all_trades if t["pnl"] > 0]
    losing_trades = [t for t in all_trades if t["pnl"] <= 0]
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades else 0.0
    total_pnl = sum(t["pnl"] for t in all_trades)
    gross_profit = sum(t["pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "regime_filter": {
            "enabled": True,
            "description": "SPY and QQQ both above their prior daily close, latched at first 5-min bar >= 10:00 ET",
            "regime_ok_days": regime_ok_days,
            "regime_fail_days": regime_fail_days,
            "total_days": len(regime_by_date),
        },
        "universe_size": len(WATCHLIST),
        "symbols_backtested": len(WATCHLIST) - len(failures),
        "symbols_skipped": failures,
        "aggregate": {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": round(win_rate, 2),
            "total_pnl_usd": round(total_pnl, 2),
            "gross_profit_usd": round(gross_profit, 2),
            "gross_loss_usd": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        },
        "per_symbol": sorted(per_symbol_summary, key=lambda x: -x["return_pct"]),
        "trades": all_trades,
    }

    with open("tjl_python_backtest_results_v2_regime.json", "w") as f:
        json.dump(result, f, indent=2)

    print()
    print("=" * 60)
    print(f"Universe: {len(WATCHLIST)} symbols ({len(failures)} skipped)")
    print(f"Regime: {regime_ok_days}/{len(regime_by_date)} days OK, {regime_fail_days} days gated out")
    print(f"Total trades: {total_trades}")
    print(f"Win rate: {win_rate:.2f}% ({len(winning_trades)}/{total_trades})")
    print(f"Total P&L: ${total_pnl:,.2f}")
    print(f"Profit factor: {profit_factor:.3f}" if profit_factor != float("inf") else "Profit factor: inf (no losing trades)")
    print("=" * 60)


if __name__ == "__main__":
    main()
