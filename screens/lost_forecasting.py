"""
Lost Forecasting, Bullish Upside cycle (Hima Reddy, after W.D. Gann).

A cycle low L1, a cycle high H, then a higher low L2. The setup triggers on
the close of the bar that confirms L2 as a 3-bar pivot, and stays listed
while it still applies: no close below L2 and the upside target
H + (L2 - L1) not reached yet. A later pivot low only replaces it when that
newer cycle is itself a valid setup.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "max_days_listed": 20,              # drop it after this many days even if it still holds
    "min_bars_l1_to_l2": 3,
    "max_bars_l1_to_l2": 60,
    "min_cycle_rally_pct": 5.0,         # cycle high at least this far above L1, filters out noise
}


def cycle(s, l2):
    earlier = [i for i in s.price_pivot_lows if i < l2 and PARAMS["min_bars_l1_to_l2"] <= l2 - i <= PARAMS["max_bars_l1_to_l2"]]
    if not earlier:
        return None
    l1 = earlier[-1]
    h = s.highest_high(l1 + 1, l2 - 1)  # the cycle high sits between the two lows, not on them
    l1p, l2p, hp = s.lows[l1], s.lows[l2], s.highs[h]
    return {"l1": l1, "l2": l2, "h": h, "l1p": l1p, "l2p": l2p, "hp": hp, "target": hp + (l2p - l1p),
            "trigger": l2 + 1}


def higher_low(x):
    return x["l2p"] > x["l1p"]


def real_cycle(x):
    return x["hp"] >= x["l1p"] * (1 + PARAMS["min_cycle_rally_pct"] / 100.0)


def holds_l2(s, x):
    return min(s.closes[x["l2"] + 1:]) > x["l2p"]


def target_open(s, x):
    return max(s.highs[x["l2"]:]) < x["target"]


def find(s):
    """Newest cycle that is still a valid setup; else the newest cycle, so near misses have a reason."""
    newest = None
    for l2 in reversed(s.price_pivot_lows):
        if s.bars_ago(l2) - 1 > PARAMS["max_days_listed"]:
            break
        x = cycle(s, l2)
        if x is None:
            continue
        newest = newest or x
        if higher_low(x) and real_cycle(x) and holds_l2(s, x) and target_open(s, x):
            return x
    return newest


def setup(g):
    return memo(g, "lost_forecasting", find)


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['trigger'])}. "
            f"L1 {x['l1p']:.2f} ({s.date(x['l1'])}), cycle high {x['hp']:.2f} ({s.date(x['h'])}), "
            f"higher low L2 {x['l2p']:.2f} ({s.date(x['l2'])}), cycle length {x['l2'] - x['l1']} bars, "
            f"target {x['target']:.2f}, last close {s.close:.2f}")


def trade(g):
    x, s = setup(g), g["structure"]
    return {"stop": x["l2p"], "target": x["target"], "plan": "stop: close below L2, target H + (L2 - L1)",
            "key": (s.date(x["l1"]), s.date(x["l2"]))}


SCREEN = Screen(
    id="lost_forecasting",
    name="Lost Forecasting, Bullish Upside",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=40,
    params=PARAMS,
    describe=describe,
    trade=trade,
    criteria=(
        "Watchlist chart setup. A 3-bar pivot low L1, a cycle high at least 5% above it, then a higher pivot low L2. "
        "It stays listed for up to 20 days while price hasn't closed below L2 or reached the cycle's "
        "upside target, the stock is above its 200-day SMA, and SPY is in an uptrend. A newer pivot low "
        "only replaces it if the newer cycle qualifies too. NEW the day L2 is confirmed, ONGOING after that."
    ),
    rules=[
        Rule("higher low (L2 above L1) confirmed in the last 20 days", lambda g: has(g, setup, higher_low)),
        Rule("cycle high 5%+ above L1", lambda g: has(g, setup, real_cycle)),
        Rule("no close below L2 since", lambda g: has(g, setup, lambda x: holds_l2(g["structure"], x))),
        Rule("upside target not reached yet", lambda g: has(g, setup, lambda x: target_open(g["structure"], x))),
        Rule("stock above its 200-day SMA", lambda g: g["structure"].sma_200 is not None and g["structure"].close > g["structure"].sma_200),
        Rule("SPY in an uptrend", market_ok),
    ],
)
