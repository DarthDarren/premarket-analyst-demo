"""
Copy this file to screens/<your_screen>.py (no leading underscore) to add a
screen. scan.py loads it automatically on the next run.

New screens start as EXPERIMENTAL. They show up in the report's Lab section
as names only, with no stops or targets, until a backtest earns them
VALIDATED status. Today every screen runs against the premarket gappers, so
rules can read any field an enriched gapper carries: gap_pct, price,
market_cap, volume, rvol, catalyst_found, catalyst_headlines,
next_earnings_date, intraday_levels{vwap, hod, lod, premarket_high,
premarket_volume} and daily_metrics{sma_200, prior_day_high, prior_close,
avg_volume_20, today_open}.
"""

from .base import EXPERIMENTAL, Rule, Screen, daily

PARAMS = {
    "min_gap_pct": 5.0,
}

SCREEN = Screen(
    id="my_screen",                     # short, unique, snake_case
    name="My Screen",
    status=EXPERIMENTAL,
    order=50,
    params=PARAMS,
    criteria="Plain-English description of the rules, quoted to the reader as-is.",
    rules=[
        Rule("gap % >= 5", lambda g: g.get("gap_pct") is not None and g["gap_pct"] >= PARAMS["min_gap_pct"]),
        Rule(
            "open > 200-day SMA",
            lambda g: daily(g, "today_open") is not None and daily(g, "sma_200") is not None
            and daily(g, "today_open") > daily(g, "sma_200"),
        ),
    ],
)
