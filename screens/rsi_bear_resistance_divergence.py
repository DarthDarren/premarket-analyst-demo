"""
Bearish Divergence in Bull Resistance (Hima Reddy, Four Zones RSI cheat sheets), as a
defensive alert on stocks Darren owns. It protects a long; it is not a short signal.

A new RSI(14) peak inside Bull Resistance (80-90) is lower than the previous RSI peak
in that zone, while price at the new peak made a higher high. The comparison is only with
the nearest earlier peak inside 80-90; if that pair doesn't diverge there is no alert.
The sheet's action is a protective sell stop under the most recent price low of the
uptrend, taken here as the latest 3-bar price pivot low before the new peak.

It stays listed while the new peak is the latest RSI peak and price hasn't closed
below the protective stop.
"""

from .base import ALERT, EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, memo

PARAMS = {
    "tiers": ["core_owned"],
    "bull_resistance_zone": [80.0, 90.0],
    "max_bars_between_peaks": 40,
}


def in_zone(r):
    lo, hi = PARAMS["bull_resistance_zone"]
    return r is not None and lo <= r <= hi


def find(s):
    """The latest RSI peak, with t1 set to the nearest earlier 80-90 peak when the two diverge."""
    if not s.rsi_peaks:
        return None
    t2 = s.rsi_peaks[-1]
    x = {"t2": t2, "r2": s.rsi[t2], "p2": s.highs[t2], "trigger": t2 + 1, "t1": None}
    t1 = next((i for i in reversed(s.rsi_peaks[:-1]) if in_zone(s.rsi[i])), None)
    if (t1 is not None and t2 - t1 <= PARAMS["max_bars_between_peaks"]
            and s.highs[t2] > s.highs[t1] and s.rsi[t2] < s.rsi[t1]):
        x.update(t1=t1, r1=s.rsi[t1], p1=s.highs[t1])
    lows = [i for i in s.price_pivot_lows if i < t2]
    x["stop_bar"] = lows[-1] if lows else None
    x["stop"] = s.lows[lows[-1]] if lows else None
    return x


def setup(g):
    return memo(g, "rsi_bear_resistance_divergence", find)


def stop_holds(s, x):
    after = s.closes[x["trigger"]:]
    return x["stop"] is not None and (not after or min(after) >= x["stop"])


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"{listing_status(s, x['trigger'])}. "
            f"RSI peak {x['r2']:.1f} at high {x['p2']:.2f} ({s.date(x['t2'])}) vs previous peak "
            f"RSI {x['r1']:.1f} at high {x['p1']:.2f} ({s.date(x['t1'])}): higher high in price, lower high in RSI. "
            f"Protective sell stop under {x['stop']:.2f} ({s.date(x['stop_bar'])}). Last close {s.close:.2f}")


SCREEN = Screen(
    id="rsi_bear_resistance_divergence",
    name="RSI Bearish Divergence in Bull Resistance",
    status=EXPERIMENTAL,
    kind=ALERT,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=61,
    max_hits=20,
    params=PARAMS,
    describe=describe,
    criteria=(
        "Portfolio alert on stocks you own (Four Zones RSI, defensive). A new RSI(14) peak inside Bull "
        "Resistance (80-90) is lower than the previous RSI peak in that zone while price made a higher "
        "high (bearish divergence). Protect the position with a sell stop under the latest 3-bar price low "
        "before the peak; this is not a short signal. It stays listed until a newer RSI peak "
        "prints or price closes below that stop. NEW the day the peak completes, ONGOING after that."
    ),
    rules=[
        Rule("new RSI peak inside Bull Resistance 80-90", lambda g: has(g, setup, lambda x: in_zone(x["r2"]))),
        Rule("lower RSI high, higher price high than the previous 80-90 peak", lambda g: has(g, setup, lambda x: x["t1"] is not None)),
        Rule("price still above the protective stop", lambda g: has(g, setup, lambda x: stop_holds(g["structure"], x))),
    ],
)
