"""
Gann Buying Point #7 (Trading Methods of W.D. Gann, Appendix C).

Buy a 50% retracement of the last advance while the main trend is up. The
advance here is the lowest low to the highest high of the last 120 days.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, market_ok, memo

PARAMS = {
    "tiers": ["core_candidate", "broad_candidate"],
    "advance_lookback": 120,
    "min_advance_pct": 15.0,
    "min_bars_since_high": 3,
    "touch_window_bars": 3,                 # the pullback reached 50% within this many days
    "tolerance_pct_of_advance": 5.0,        # how close to 50% counts, as % of the advance
}


def find(s):
    n = PARAMS["advance_lookback"]
    if len(s.closes) < n:
        return None
    start = s.last - n + 1
    b = s.highest_high(start, s.last)
    if s.bars_ago(b) < PARAMS["min_bars_since_high"]:
        return None
    a = s.lowest_low(start, b)
    low, high = s.lows[a], s.highs[b]
    span = high - low
    return {"a": a, "b": b, "low": low, "high": high, "half": low + span / 2,
            "tol": span * PARAMS["tolerance_pct_of_advance"] / 100.0,
            "advance_pct": 100.0 * span / low if low else 0.0}


def setup(g):
    return memo(g, "gann_bp7", find)


def touched_half(g):
    x, s = setup(g), g["structure"]
    return min(s.lows[-PARAMS["touch_window_bars"]:]) <= x["half"] + x["tol"]


def holding_half(g):
    x, s = setup(g), g["structure"]
    return min(s.closes[x["b"]:]) >= x["half"] - x["tol"]


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"advance {x['low']:.2f} ({s.date(x['a'])}) to {x['high']:.2f} ({s.date(x['b'])}), "
            f"+{x['advance_pct']:.0f}%, 50% level {x['half']:.2f}, last close {s.close:.2f}")


SCREEN = Screen(
    id="gann_bp7",
    name="Gann Buying Point #7, 50% pullback",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=42,
    params=PARAMS,
    describe=describe,
    criteria=(
        "Watchlist chart setup. The main trend is up (50-day SMA above 200-day SMA) after an "
        "advance of 15%+ over the last 120 days. Price has pulled back to about 50% of that "
        "advance in the last 3 days without closing below it, and SPY is in an uptrend."
    ),
    rules=[
        Rule("main trend up (50-day SMA above 200-day)", lambda g: g["structure"].sma_50 > g["structure"].sma_200),
        Rule("advance of 15%+ into the high", lambda g: setup(g) is not None and setup(g)["advance_pct"] >= PARAMS["min_advance_pct"]),
        Rule("pullback reached the 50% level", touched_half),
        Rule("no close below the 50% level", holding_half),
        Rule("SPY in an uptrend", market_ok),
    ],
)
