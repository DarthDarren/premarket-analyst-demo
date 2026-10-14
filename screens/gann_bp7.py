"""
Gann Buying Point #7 (Trading Methods of W.D. Gann, Appendix C).

Buy a 50% retracement of the last advance while the main trend is up. The
advance here is the lowest low to the highest high of the last 120 days.
The setup stays listed while price holds the 50% level and hasn't made a new
high (a new high starts a new advance).
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "advance_lookback": 120,
    "min_advance_pct": 15.0,
    "min_bars_since_high": 3,
    "max_days_listed": 20,                  # drop it after this many days even if it still holds
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
    half = low + span / 2
    tol = span * PARAMS["tolerance_pct_of_advance"] / 100.0
    touch = next((i for i in range(b + 1, s.last + 1) if s.lows[i] <= half + tol), None)
    return {"a": a, "b": b, "low": low, "high": high, "half": half, "tol": tol, "touch": touch,
            "advance_pct": 100.0 * span / low if low else 0.0}


def setup(g):
    return memo(g, "gann_bp7", find)


def touched_half(g):
    s = g["structure"]
    return has(g, setup, lambda x: x["touch"] is not None and s.bars_ago(x["touch"]) <= PARAMS["max_days_listed"])


def holding_half(g):
    s = g["structure"]
    return has(g, setup, lambda x: min(s.closes[x["b"]:]) >= x["half"] - x["tol"])


def trade(g):
    x, s = setup(g), g["structure"]
    return {"stop": x["half"] - x["tol"], "target": x["high"], "plan": "stop: close below the 50% level, target the prior high",
            "key": (s.date(x["a"]), s.date(x["b"]))}


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['touch'])}. "
            f"advance {x['low']:.2f} ({s.date(x['a'])}) to {x['high']:.2f} ({s.date(x['b'])}), "
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
    trade=trade,
    criteria=(
        "Watchlist chart setup. The main trend is up (50-day SMA above 200-day SMA) after an "
        "advance of 15%+ over the last 120 days. Price pulled back to about 50% of that advance "
        "without closing below it, and SPY is in an uptrend. It stays listed for up to 20 days "
        "while the 50% level holds and until a new high. NEW when it first reaches 50%, ONGOING after that."
    ),
    rules=[
        Rule("main trend up (50-day SMA above 200-day)", lambda g: None not in (g["structure"].sma_50, g["structure"].sma_200) and g["structure"].sma_50 > g["structure"].sma_200),
        Rule("advance of 15%+ into the high", lambda g: has(g, setup, lambda x: x["advance_pct"] >= PARAMS["min_advance_pct"])),
        Rule("pullback reached the 50% level in the last 20 days", touched_half),
        Rule("no close below the 50% level", holding_half),
        Rule("SPY in an uptrend", market_ok),
    ],
)
