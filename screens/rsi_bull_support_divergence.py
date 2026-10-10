"""
RSI Bullish Divergence in Bull Support (Hima Reddy, RSI Power Zones).

In a bull range RSI(14) tends to bottom in the 40-50 Bull Support zone. A
fresh RSI trough in that zone, at a lower price low than the prior RSI trough
but a higher RSI value, is a bullish divergence.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, market_ok, memo

PARAMS = {
    "tiers": ["core_candidate", "broad_candidate"],
    "bull_support_zone": [40.0, 50.0],
    "max_bars_since_trough_confirmed": 1,
    "min_bars_between_troughs": 5,
    "max_bars_between_troughs": 40,
    "bull_range_rsi_high": 70.0,          # RSI reached this within bull_range_lookback bars
    "bull_range_lookback": 60,
}


def price_low_near(s, i):
    return min(s.lows[max(0, i - 1):i + 2])


def find(s):
    troughs = [i for i in s.rsi_troughs if s.bars_ago(i) - 1 <= PARAMS["max_bars_since_trough_confirmed"]]
    if not troughs:
        return None
    t2 = troughs[-1]
    earlier = [i for i in s.rsi_troughs
               if PARAMS["min_bars_between_troughs"] <= t2 - i <= PARAMS["max_bars_between_troughs"]]
    if not earlier:
        return None
    # Compare against the deepest RSI trough in the window, the one a divergence is measured from.
    t1 = min(earlier, key=lambda i: s.rsi[i])
    return {"t1": t1, "t2": t2, "r1": s.rsi[t1], "r2": s.rsi[t2],
            "p1": price_low_near(s, t1), "p2": price_low_near(s, t2)}


def setup(g):
    return memo(g, "rsi_bull_support_divergence", find)


def in_zone(g):
    lo, hi = PARAMS["bull_support_zone"]
    return lo <= setup(g)["r2"] <= hi


def bull_range(g):
    s = g["structure"]
    recent = [r for r in s.rsi[-PARAMS["bull_range_lookback"]:] if r is not None]
    return bool(recent) and max(recent) >= PARAMS["bull_range_rsi_high"]


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"RSI trough {x['r2']:.1f} at price low {x['p2']:.2f} ({s.date(x['t2'])}) vs "
            f"RSI {x['r1']:.1f} at {x['p1']:.2f} ({s.date(x['t1'])}): lower low in price, higher low in RSI")


SCREEN = Screen(
    id="rsi_bull_support_divergence",
    name="RSI Bullish Divergence in Bull Support",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=41,
    params=PARAMS,
    describe=describe,
    criteria=(
        "Watchlist chart setup. RSI(14) just put in a trough inside the 40-50 Bull Support zone. "
        "Price made a lower low than at the previous RSI trough while RSI made a higher low "
        "(bullish divergence). RSI reached 70+ in the last 60 days, so the stock is in a bull "
        "range, and SPY is in an uptrend."
    ),
    rules=[
        Rule("fresh RSI trough just confirmed", lambda g: setup(g) is not None),
        Rule("RSI trough inside Bull Support 40-50", in_zone),
        Rule("lower price low with higher RSI low", lambda g: setup(g)["p2"] < setup(g)["p1"] and setup(g)["r2"] > setup(g)["r1"]),
        Rule("RSI hit 70+ in last 60 days (bull range)", bull_range),
        Rule("SPY in an uptrend", market_ok),
    ],
)
