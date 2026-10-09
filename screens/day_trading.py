"""Trend Join Long, the day trading screen. Rules from WATCHLIST_CRITERIA.md."""

from .base import VALIDATED, Rule, Screen, daily

PARAMS = {
    "min_gap_pct": 3.0,
    "min_price": 3.0,
    "min_market_cap": 1_000_000_000,
    "min_rvol": 1.5,
}

SCREEN = Screen(
    id="day_trading",
    name="Day Trading Watchlist: Trend Join Long",
    status=VALIDATED,
    order=10,
    flag="day_eligible",
    rules_key="day_trading_rules",
    builtin=True,
    params=PARAMS,
    criteria=(
        "Trend Join Long. Gap up over 3%, price over $3, market cap over $1B, "
        "premarket RVOL over 1.5, price breaking above yesterday's high. Backtest is "
        "54.6% win rate, 1.59 profit factor, 280 trades."
    ),
    backtest={"win_rate": 0.546, "profit_factor": 1.59, "trades": 280},
    rules=[
        Rule("gap % > 3", lambda g: g.get("gap_pct") is not None and g["gap_pct"] > PARAMS["min_gap_pct"]),
        Rule("price > $3", lambda g: g.get("price") is not None and g["price"] > PARAMS["min_price"]),
        Rule("market cap > $1B", lambda g: g.get("market_cap") is not None and g["market_cap"] > PARAMS["min_market_cap"]),
        Rule("RVOL > 1.5", lambda g: g.get("rvol") is not None and g["rvol"] > PARAMS["min_rvol"]),
        Rule(
            "price > prior day high",
            lambda g: g.get("price") is not None and daily(g, "prior_day_high") is not None
            and g["price"] > daily(g, "prior_day_high"),
        ),
    ],
)
