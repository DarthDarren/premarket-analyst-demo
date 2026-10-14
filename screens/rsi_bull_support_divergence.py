"""
Bullish Divergence in Bull Support (Hima Reddy, Four Zones RSI cheat sheets, offensive buy).

A new RSI(14) trough inside Bull Support (40-50) that is higher than the previous
RSI trough, while price at the new trough made a lower low than price at the
previous trough. The stock has to be in a bull range: RSI visited Bull Resistance
(80+) before this trough. The trough is complete on the next bar; the sheet's
trade is a buy limit at that completing candle's close, a stop below its low, and
a target of 2 units of reward per unit of risk.

The setup stays listed until a close below the stop or the 2R target is reached.
Only a newer completed divergence replaces it.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "bull_support_zone": [40.0, 50.0],
    "bull_resistance_min": 80.0,
    "bull_range_lookback": 60,            # bars before the new trough searched for the 80+ visit
    "min_bars_between_troughs": 5,
    "max_bars_between_troughs": 40,
    "reward_risk": 2.0,
}


def partner(s, k):
    """The nearest earlier RSI trough the new one (s.rsi_troughs[k]) diverges from: higher RSI, lower price low."""
    t2 = s.rsi_troughs[k]
    for t1 in reversed(s.rsi_troughs[:k]):
        if t2 - t1 < PARAMS["min_bars_between_troughs"]:
            continue
        if t2 - t1 > PARAMS["max_bars_between_troughs"]:
            return None
        if s.rsi[t2] > s.rsi[t1] and s.lows[t2] < s.lows[t1]:
            return t1
    return None


def divergence(s, k):
    t2 = s.rsi_troughs[k]
    c = t2 + 1                     # the candle that completes the trough
    if c > s.last:
        return None
    t1 = partner(s, k)
    if t1 is None:
        return None
    entry, stop = s.closes[c], s.lows[c]
    risk = entry - stop
    if risk <= 0:
        return None
    return {"t1": t1, "t2": t2, "r1": s.rsi[t1], "r2": s.rsi[t2], "p1": s.lows[t1], "p2": s.lows[t2],
            "trigger": c, "entry": entry, "stop": stop, "target": entry + PARAMS["reward_risk"] * risk}


def find(s):
    """The newest completed divergence. A later trough that isn't one doesn't replace it."""
    for k in reversed(range(len(s.rsi_troughs))):
        x = divergence(s, k)
        if x is not None:
            return x
    return None


def setup(g):
    return memo(g, "rsi_bull_support_divergence", find)


def in_zone(x):
    lo, hi = PARAMS["bull_support_zone"]
    return lo <= x["r2"] <= hi


def bull_range(s, x):
    before = [r for r in s.rsi[max(0, x["t2"] - PARAMS["bull_range_lookback"]):x["t2"]] if r is not None]
    return bool(before) and max(before) >= PARAMS["bull_resistance_min"]


def stop_holds(s, x):
    after = s.closes[x["trigger"] + 1:]
    return not after or min(after) >= x["stop"]


def target_open(s, x):
    after = s.highs[x["trigger"] + 1:]
    return not after or max(after) < x["target"]


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['trigger'])}. "
            f"RSI trough {x['r2']:.1f} at low {x['p2']:.2f} ({s.date(x['t2'])}) vs previous trough "
            f"RSI {x['r1']:.1f} at low {x['p1']:.2f} ({s.date(x['t1'])}): lower low in price, higher low in RSI. "
            f"Buy limit {x['entry']:.2f} (close {s.date(x['trigger'])}), stop {x['stop']:.2f}, "
            f"2R target {x['target']:.2f}. Last close {s.close:.2f}")


def trade(g):
    x, s = setup(g), g["structure"]
    return {"entry": x["entry"], "entry_date": s.date(x["trigger"]), "stop": x["stop"], "target": x["target"],
            "plan": "buy the completing candle's close, stop: close below its low, target 2R",
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
        "Watchlist chart setup (Four Zones RSI, offensive buy). A new RSI(14) trough inside Bull Support "
        "(40-50) is higher than the previous RSI trough while price made a lower low, and RSI visited Bull "
        "Resistance (80+) in the 60 days before it. Buy limit at the close of the candle that completes the "
        "trough, stop below that candle's low, target 2x the risk. It stays listed until a close below the "
        "stop or the target is hit. App market gate, not part of the sheet: SPY must be in an uptrend. "
        "NEW the day the trough completes, ONGOING after that."
    ),
    rules=[
        Rule("bullish divergence: higher RSI trough, lower price low", lambda g: setup(g) is not None),
        Rule("new trough inside Bull Support 40-50", lambda g: has(g, setup, in_zone)),
        Rule("RSI visited Bull Resistance 80+ before the trough", lambda g: has(g, setup, lambda x: bull_range(g["structure"], x))),
        Rule("no close below the stop since", lambda g: has(g, setup, lambda x: stop_holds(g["structure"], x))),
        Rule("2R target not reached yet", lambda g: has(g, setup, lambda x: target_open(g["structure"], x))),
        Rule("SPY in an uptrend (app market gate)", market_ok),
    ],
)
