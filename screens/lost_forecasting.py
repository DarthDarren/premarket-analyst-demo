"""
Lost Forecasting, Bullish Upside forecast (Hima Reddy, Lost Forecasting daily trading guide,
forecast type 1 only).

Pick a cycle: 3-bar price low L1, the price high H between the lows, and a higher 3-bar
price low L2. Clone the L1-L2 line onto H for the forecast:
    price target = high[H] + (low[L2] - low[L1])
    time target  = bar H + (L2 - L1)
The forecast can first be drawn at the close of the candle that completes L2 (bar L2 + 1),
which is the buy limit. The stop is below L2; a close below low[L2] voids the forecast,
and so does reaching the price target. A newer pivot low doesn't cancel it unless the
newer cycle is itself a valid forecast.
"""

from datetime import date, timedelta

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "min_bars_l1_to_l2": 3,
    "max_bars_l1_to_l2": 60,
}


def cycle(s, k):
    """The cycle ending at price pivot low s.price_pivot_lows[k], with L1 the nearest prior pivot low."""
    l2 = s.price_pivot_lows[k]
    l1 = next((i for i in reversed(s.price_pivot_lows[:k])
               if PARAMS["min_bars_l1_to_l2"] <= l2 - i <= PARAMS["max_bars_l1_to_l2"]), None)
    if l1 is None or l2 + 1 > s.last:
        return None
    h = s.highest_high(l1 + 1, l2 - 1)  # the cycle high sits between the two lows, not on them
    l1p, l2p, hp = s.lows[l1], s.lows[l2], s.highs[h]
    return {"l1": l1, "l2": l2, "h": h, "l1p": l1p, "l2p": l2p, "hp": hp,
            "target": hp + (l2p - l1p), "time_target": h + (l2 - l1),
            "trigger": l2 + 1, "entry": s.closes[l2 + 1]}


def find(s):
    """Newest cycle that is still a live forecast; else the newest cycle, so near misses have a reason."""
    n = len(s.closes)
    # Suffix min close and max high, so each candidate's "still valid" check is O(1).
    min_close, max_high = [0.0] * (n + 1), [0.0] * (n + 1)
    min_close[n], max_high[n] = float("inf"), float("-inf")
    for i in range(n - 1, -1, -1):
        min_close[i] = min(s.closes[i], min_close[i + 1])
        max_high[i] = max(s.highs[i], max_high[i + 1])
    newest = None
    for k in reversed(range(len(s.price_pivot_lows))):
        x = cycle(s, k)
        if x is None:
            continue
        newest = newest or x
        if x["l2p"] > x["l1p"] and min_close[x["l2"] + 1] >= x["l2p"] and max_high[x["l2"]] < x["target"]:
            return x
    return newest


def setup(g):
    return memo(g, "lost_forecasting", find)


def higher_low(x):
    return x["l2p"] > x["l1p"]


def holds_l2(s, x):
    return min(s.closes[x["l2"] + 1:]) >= x["l2p"]


def target_open(s, x):
    return max(s.highs[x["l2"]:]) < x["target"]


def bar_date(s, i):
    """Date of bar i, counting weekdays past the last bar for a time target still in the future."""
    if i <= s.last:
        return s.date(i)
    d = date.fromisoformat(s.date(s.last))
    for _ in range(i - s.last):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d.isoformat()


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['trigger'])}. "
            f"L1 {x['l1p']:.2f} ({s.date(x['l1'])}), cycle high {x['hp']:.2f} ({s.date(x['h'])}), "
            f"higher low L2 {x['l2p']:.2f} ({s.date(x['l2'])}). Buy limit {x['entry']:.2f}, stop below {x['l2p']:.2f}, "
            f"price target {x['target']:.2f}, time target about {bar_date(s, x['time_target'])}. Last close {s.close:.2f}")


def trade(g):
    x, s = setup(g), g["structure"]
    return {"entry": x["entry"], "entry_date": s.date(x["trigger"]), "stop": x["l2p"], "target": x["target"],
            "plan": "buy the close of the bar completing L2, stop: close below L2, target H + (L2 - L1)",
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
        "Watchlist chart setup (Lost Forecasting, Bullish Upside). A 3-bar price low L1, the high H between, "
        "and a higher 3-bar price low L2. Price target H + (L2 - L1), time target the same number of bars "
        "after H. Buy limit at the close of the candle that completes L2, stop below L2. It stays listed until "
        "a close below L2 or the price target is hit. App market gate, not part of the guide: SPY must be in "
        "an uptrend. NEW the day L2 completes, ONGOING after that."
    ),
    rules=[
        Rule("cycle with a higher low (L2 above L1)", lambda g: has(g, setup, higher_low)),
        Rule("no close below L2 since", lambda g: has(g, setup, lambda x: holds_l2(g["structure"], x))),
        Rule("price target not reached yet", lambda g: has(g, setup, lambda x: target_open(g["structure"], x))),
        Rule("SPY in an uptrend (app market gate)", market_ok),
    ],
)
