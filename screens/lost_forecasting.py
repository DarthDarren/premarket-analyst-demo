"""
Lost Forecasting, Bullish Upside cycle (Hima Reddy, after W.D. Gann).

A cycle low L1, a cycle high H, then a higher low L2. The setup triggers on
the close of the bar that confirms L2 as a 3-bar pivot. The source material's
upside price target is H + (L2 - L1), and that target is checked here only so
a name that already got there doesn't show up as fresh.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, market_ok, memo

PARAMS = {
    "tiers": ["core_candidate", "broad_candidate"],
    "max_bars_since_l2_confirmed": 1,   # 0 = confirmed on the last finished day
    "min_bars_l1_to_l2": 3,
    "max_bars_l1_to_l2": 60,
    "min_cycle_rally_pct": 5.0,         # cycle high at least this far above L1, filters out noise
}


def find(s):
    lows = [i for i in s.price_pivot_lows if s.bars_ago(i) - 1 <= PARAMS["max_bars_since_l2_confirmed"]]
    if not lows:
        return None
    l2 = lows[-1]
    earlier = [i for i in s.price_pivot_lows if i < l2 and PARAMS["min_bars_l1_to_l2"] <= l2 - i <= PARAMS["max_bars_l1_to_l2"]]
    if not earlier:
        return None
    l1 = earlier[-1]
    h = s.highest_high(l1, l2)
    l1p, l2p, hp = s.lows[l1], s.lows[l2], s.highs[h]
    return {"l1": l1, "l2": l2, "h": h, "l1p": l1p, "l2p": l2p, "hp": hp, "target": hp + (l2p - l1p)}


def setup(g):
    return memo(g, "lost_forecasting", find)


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"L1 {x['l1p']:.2f} ({s.date(x['l1'])}), cycle high {x['hp']:.2f} ({s.date(x['h'])}), "
            f"higher low L2 {x['l2p']:.2f} ({s.date(x['l2'])}), cycle length {x['l2'] - x['l1']} bars")


SCREEN = Screen(
    id="lost_forecasting",
    name="Lost Forecasting, Bullish Upside",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=40,
    params=PARAMS,
    describe=describe,
    criteria=(
        "Watchlist chart setup. A 3-bar pivot low L1, a cycle high at least 5% above it, then a higher pivot low L2 "
        "that was just confirmed by the last finished day's bar. Price is still above L2 and "
        "hasn't reached the cycle's upside target yet, the stock is above its 200-day SMA, "
        "and SPY is in an uptrend."
    ),
    rules=[
        Rule("fresh higher low (L2 above L1) just confirmed", lambda g: setup(g) is not None and setup(g)["l2p"] > setup(g)["l1p"]),
        Rule("cycle high 5%+ above L1", lambda g: setup(g)["hp"] >= setup(g)["l1p"] * (1 + PARAMS["min_cycle_rally_pct"] / 100.0)),
        Rule("price still above L2", lambda g: g["structure"].close > setup(g)["l2p"]),
        Rule("upside target not reached yet", lambda g: max(g["structure"].highs[setup(g)["l2"]:]) < setup(g)["target"]),
        Rule("stock above its 200-day SMA", lambda g: g["structure"].close > g["structure"].sma_200),
        Rule("SPY in an uptrend", market_ok),
    ],
)
