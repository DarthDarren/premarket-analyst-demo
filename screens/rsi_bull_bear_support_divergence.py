"""
Bullish Divergence in Bear Support (Hima Reddy, Four Zones RSI and Advanced RSI Power Zones sheets).

A new RSI(14) trough inside Bear Support (20-30) that is higher than the previous RSI trough,
while price at the new trough made a lower low than price at the previous trough. The Four
Zones sheet uses it defensively (protect profits on shorts); the Advanced sheet lists it as a
long entry, less reliable than the same divergence in Bull Support. It is traded here the way
the Bull Support setup is: a buy limit at the close of the candle that completes the trough, a
stop below that candle's low, and a target of 2 units of reward per unit of risk.

Pairing, completion and listing work exactly as in rsi_bull_support_divergence: only the nearest
earlier trough counts, and the setup stays listed until a close below the stop or the 2R target.
"""

from . import rsi_bull_support_divergence as bull
from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "bear_support_zone": [20.0, 30.0],     # trough pairing and the 2R target come from the Bull Support screen's PARAMS
}


def in_zone(x):
    lo, hi = PARAMS["bear_support_zone"]
    return lo <= x["r2"] <= hi


def live(s, x):
    return in_zone(x) and bull.stop_holds(s, x) and bull.target_open(s, x)


def find(s):
    """The newest divergence that is still a live setup; else the newest divergence, so near misses have a reason."""
    newest = None
    for k in reversed(range(len(s.rsi_troughs))):
        x = bull.divergence(s, k)
        if x is None:
            continue
        newest = newest or x
        if live(s, x):
            return x
    return newest


def setup(g):
    return memo(g, "rsi_bull_bear_support_divergence", find)


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['trigger'])}. "
            f"RSI trough {x['r2']:.1f} in Bear Support at low {x['p2']:.2f} ({s.date(x['t2'])}) vs previous trough "
            f"RSI {x['r1']:.1f} at low {x['p1']:.2f} ({s.date(x['t1'])}): lower low in price, higher low in RSI. "
            f"Buy limit {x['entry']:.2f} (close {s.date(x['trigger'])}), stop {x['stop']:.2f}, "
            f"2R target {x['target']:.2f}. Last close {s.close:.2f}")


def trade(g):
    x, s = setup(g), g["structure"]
    return {"entry": x["entry"], "entry_date": s.date(x["trigger"]), "stop": x["stop"], "target": x["target"],
            "plan": "buy the completing candle's close, stop: close below its low, target 2R",
            "key": (s.date(x["t1"]), s.date(x["t2"]))}


SCREEN = Screen(
    id="rsi_bull_bear_support_divergence",
    name="RSI Bullish Divergence in Bear Support",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=44,
    params=PARAMS,
    describe=describe,
    trade=trade,
    criteria=(
        "Watchlist chart setup (Four Zones / Advanced RSI Power Zones). A new RSI(14) trough inside Bear Support "
        "(20-30) is higher than the previous (nearest earlier) RSI trough while price made a lower low. The Four "
        "Zones sheet treats it as defensive and the Advanced sheet ranks it below the Bull Support divergence, so "
        "it is a lower-reliability bottom attempt in a weak stock. Buy limit at the close of the candle that "
        "completes the trough, stop below that candle's low, target 2x the risk. It stays listed until a close "
        "below the stop or the target is hit. App market gate, not part of the sheet: SPY must be in an uptrend. "
        "NEW the day the trough completes, ONGOING after that."
    ),
    rules=[
        Rule("bullish divergence: higher RSI trough, lower price low", lambda g: setup(g) is not None),
        Rule("new trough inside Bear Support 20-30", lambda g: has(g, setup, in_zone)),
        Rule("no close below the stop since", lambda g: has(g, setup, lambda x: bull.stop_holds(g["structure"], x))),
        Rule("2R target not reached yet", lambda g: has(g, setup, lambda x: bull.target_open(g["structure"], x))),
        Rule("SPY in an uptrend (app market gate)", market_ok),
    ],
)
