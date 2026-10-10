"""
RSI Bearish Divergence in Bull Resistance (Hima Reddy, RSI Power Zones), as
a portfolio alert on stocks Darren owns.

In a bull range RSI(14) tends to top in the 80-90 Bull Resistance zone. A
fresh RSI peak at a higher price high than a prior peak that reached that
zone, but with a lower RSI value, is a bearish divergence.
"""

from .base import ALERT, EXPERIMENTAL, WATCHLIST, Rule, Screen, memo

PARAMS = {
    "tiers": ["core_owned"],
    "bull_resistance_min": 80.0,
    "max_bars_since_peak_confirmed": 1,
    "min_bars_between_peaks": 5,
    "max_bars_between_peaks": 40,
}


def price_high_near(s, i):
    return max(s.highs[max(0, i - 1):i + 2])


def find(s):
    peaks = [i for i in s.rsi_peaks if s.bars_ago(i) - 1 <= PARAMS["max_bars_since_peak_confirmed"]]
    if not peaks:
        return None
    t2 = peaks[-1]
    earlier = [i for i in s.rsi_peaks
               if PARAMS["min_bars_between_peaks"] <= t2 - i <= PARAMS["max_bars_between_peaks"]]
    if not earlier:
        return None
    t1 = max(earlier, key=lambda i: s.rsi[i])
    return {"t1": t1, "t2": t2, "r1": s.rsi[t1], "r2": s.rsi[t2],
            "p1": price_high_near(s, t1), "p2": price_high_near(s, t2)}


def setup(g):
    return memo(g, "rsi_bear_resistance_divergence", find)


def describe(g):
    x, s = setup(g), g["structure"]
    return (f"RSI peak {x['r2']:.1f} at price high {x['p2']:.2f} ({s.date(x['t2'])}) vs "
            f"RSI {x['r1']:.1f} at {x['p1']:.2f} ({s.date(x['t1'])}): higher high in price, lower high in RSI. "
            f"Last close {s.close:.2f}")


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
        "Portfolio alert on stocks you own. RSI(14) just put in a peak. An earlier RSI peak in the "
        "last 40 days reached the 80+ Bull Resistance zone, and price has now made a higher high "
        "while RSI made a lower high (bearish divergence), a sign the advance is losing steam."
    ),
    rules=[
        Rule("fresh RSI peak just confirmed", lambda g: setup(g) is not None),
        Rule("earlier RSI peak reached Bull Resistance 80+", lambda g: setup(g)["r1"] >= PARAMS["bull_resistance_min"]),
        Rule("higher price high with lower RSI high", lambda g: setup(g)["p2"] > setup(g)["p1"] and setup(g)["r2"] < setup(g)["r1"]),
    ],
)
