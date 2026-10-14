"""Swing gappers screen. Rules from WATCHLIST_CRITERIA.md."""

from .base import VALIDATED, Rule, Screen, daily

PARAMS = {
    "min_gap_pct": 8.0,
    "min_price": 3.0,
    "min_market_cap": 800_000_000,
}

SCREEN = Screen(
    id="swing",
    name="Swing Watchlist",
    status=VALIDATED,
    order=20,
    flag="swing_eligible",
    rules_key="swing_rules",
    builtin=True,
    params=PARAMS,
    criteria=(
        "Gap up 8% or more, price over $3, open above yesterday's high, open above "
        "the 200 day SMA (before the bell, the premarket price stands in for the open), "
        "market cap at or above $800M, and a real catalyst: earnings on the gap, or a "
        "matching headline since yesterday afternoon. Entry and exit management is still being "
        "built, these are starter ideas only, no stops or targets attached."
    ),
    rules=[
        Rule("gap % >= 8", lambda g: g.get("gap_pct") is not None and g["gap_pct"] >= PARAMS["min_gap_pct"]),
        Rule("price > $3", lambda g: g.get("price") is not None and g["price"] > PARAMS["min_price"]),
        Rule(
            "open > prior day high",
            lambda g: daily(g, "today_open") is not None and daily(g, "prior_day_high") is not None
            and daily(g, "today_open") > daily(g, "prior_day_high"),
        ),
        Rule(
            "open > 200-day SMA",
            lambda g: daily(g, "today_open") is not None and daily(g, "sma_200") is not None
            and daily(g, "today_open") > daily(g, "sma_200"),
        ),
        Rule("market cap >= $800M", lambda g: g.get("market_cap") is not None and g["market_cap"] >= PARAMS["min_market_cap"]),
        Rule("real catalyst", lambda g: bool(g.get("catalyst_found"))),
    ],
)
