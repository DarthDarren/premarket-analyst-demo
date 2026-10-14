"""
RSI Bullish Divergence in Bull Support (Hima Reddy, RSI Power Zones).

In a bull range RSI(14) tends to bottom in the 40-50 Bull Support zone. A
fresh RSI trough in that zone, at a lower price low than the deepest RSI
trough of the prior 5-40 days but with a higher RSI value, is a bullish
divergence. Price at a trough is the lowest low of the trough bar and the bar
on each side. It stays listed while price holds above that low; a newer RSI
trough only replaces it when it is a valid divergence too.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "bull_support_zone": [40.0, 50.0],
    "max_days_listed": 20,                # drop it after this many days even if it still holds
    "min_bars_between_troughs": 5,
    "max_bars_between_troughs": 40,
    "bull_range_rsi_high": 70.0,          # RSI reached this within bull_range_lookback bars
    "bull_range_lookback": 60,
}


def price_low_near(s, i):
    return min(s.lows[max(0, i - 1):i + 2])


def pair(s, t2):
    earlier = [i for i in s.rsi_troughs
               if PARAMS["min_bars_between_troughs"] <= t2 - i <= PARAMS["max_bars_between_troughs"]]
    if not earlier:
        return None
    # Measured from the deepest RSI trough in the window, the low the divergence is judged against.
    t1 = min(earlier, key=lambda i: s.rsi[i])
    return {"t1": t1, "t2": t2, "r1": s.rsi[t1], "r2": s.rsi[t2],
            "p1": price_low_near(s, t1), "p2": price_low_near(s, t2), "trigger": t2 + 1}


def in_zone(x):
    lo, hi = PARAMS["bull_support_zone"]
    return lo <= x["r2"] <= hi


def diverges(x):
    return x["p2"] < x["p1"] and x["r2"] > x["r1"]


def holds_low(s, x):
    return min(s.closes[x["t2"] + 1:]) >= x["p2"]


def find(s):
    """Newest trough that is still a valid divergence; else the newest trough, so near misses have a reason."""
    newest = None
    for t2 in reversed(s.rsi_troughs):
        if s.bars_ago(t2) - 1 > PARAMS["max_days_listed"]:
            break
        x = pair(s, t2)
        if x is None:
            continue
        newest = newest or x
        if in_zone(x) and diverges(x) and holds_low(s, x):
            return x
    return newest


def setup(g):
    return memo(g, "rsi_bull_support_divergence", find)


def bull_range(g):
    s = g["structure"]
    recent = [r for r in s.rsi[-PARAMS["bull_range_lookback"]:] if r is not None]
    return bool(recent) and max(recent) >= PARAMS["bull_range_rsi_high"]


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['trigger'])}. "
            f"RSI trough {x['r2']:.1f} at price low {x['p2']:.2f} ({s.date(x['t2'])}) vs "
            f"RSI {x['r1']:.1f} at {x['p1']:.2f} ({s.date(x['t1'])}): lower low in price, higher low in RSI. "
            f"Last close {s.close:.2f}")


def trade(g):
    x, s = setup(g), g["structure"]
    return {"stop": x["p2"], "target": None, "plan": "stop: close below the divergence low, no target (time exit)",
            "key": (s.date(x["t1"]), s.date(x["t2"]))}


SCREEN = Screen(
    id="rsi_bull_support_divergence",
    name="RSI Bullish Divergence in Bull Support",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=41,
    params=PARAMS,
    describe=describe,
    trade=trade,
    criteria=(
        "Watchlist chart setup. RSI(14) put in a trough inside the 40-50 Bull Support zone. "
        "Price made a lower low than at the deepest RSI trough of the prior 5-40 days while RSI made "
        "a higher low (bullish divergence). RSI reached 70+ in the last 60 days, so the stock is in a bull "
        "range, and SPY is in an uptrend. It stays listed for up to 20 days while price hasn't closed "
        "below the divergence low (the lowest low of the trough bar and the bar on each side). "
        "NEW the day the trough is confirmed, ONGOING after that."
    ),
    rules=[
        Rule("RSI trough confirmed in the last 20 days", lambda g: setup(g) is not None),
        Rule("RSI trough inside Bull Support 40-50", lambda g: has(g, setup, in_zone)),
        Rule("lower price low with higher RSI low", lambda g: has(g, setup, diverges)),
        Rule("no close below the divergence low since", lambda g: has(g, setup, lambda x: holds_low(g["structure"], x))),
        Rule("RSI hit 70+ in last 60 days (bull range)", bull_range),
        Rule("SPY in an uptrend", market_ok),
    ],
)
