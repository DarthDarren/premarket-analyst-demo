"""
Gann Selling Points #4 and #6 (Trading Methods of W.D. Gann, Appendix C),
as a portfolio alert on stocks Darren owns.

After an advance, the first decline from the top that is bigger in price
(#4) or longer in time (#6) than the greatest reaction during the advance
says the trend has likely changed.
"""

from daily_structure import reactions

from .base import ALERT, EXPERIMENTAL, WATCHLIST, Rule, Screen, memo

PARAMS = {
    "tiers": ["core_owned"],
    "advance_lookback": 120,
    "min_advance_pct": 15.0,
    "min_bars_since_high": 2,
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
    rx = reactions(s, a, b)
    if not rx:
        return None
    trough = s.lowest_low(b + 1, s.last)
    top = s.highs[b]
    return {
        "a": a, "b": b, "low": s.lows[a], "top": top,
        "advance_pct": 100.0 * (top - s.lows[a]) / s.lows[a],
        "max_reaction_pct": max(r["size_pct"] for r in rx),
        "max_reaction_bars": max(r["bars"] for r in rx),
        "decline_pct": 100.0 * (top - s.lows[trough]) / top,
        "decline_bars": s.last - b,
    }


def setup(g):
    return memo(g, "gann_selling_points", find)


def size_exceeded(g):
    x = setup(g)
    return x["decline_pct"] > x["max_reaction_pct"]


def time_exceeded(g):
    x = setup(g)
    return x["decline_bars"] > x["max_reaction_bars"]


def describe(g):
    x, s = setup(g), g["structure"]
    which = [w for w, hit in (("#4 size", size_exceeded(g)), ("#6 time", time_exceeded(g))) if hit]
    return (f"top {x['top']:.2f} ({s.date(x['b'])}) after a +{x['advance_pct']:.0f}% advance. "
            f"Decline so far {x['decline_pct']:.1f}% over {x['decline_bars']} days vs the biggest reaction in "
            f"the advance of {x['max_reaction_pct']:.1f}% and the longest of {x['max_reaction_bars']} days. "
            f"Triggered: {', '.join(which)}. Last close {s.close:.2f}")


SCREEN = Screen(
    id="gann_selling_points",
    name="Gann Selling Points #4/#6, trend change",
    status=EXPERIMENTAL,
    kind=ALERT,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=60,
    max_hits=20,
    params=PARAMS,
    describe=describe,
    criteria=(
        "Portfolio alert on stocks you own. After an advance of 15%+ into a high within the last "
        "120 days, the decline from that high is now bigger in price (Selling Point #4) or longer "
        "in time (Selling Point #6) than the biggest pullback during the advance. Gann reads that "
        "as a likely change in trend."
    ),
    rules=[
        Rule("advance of 15%+ into a recent high", lambda g: setup(g) is not None and setup(g)["advance_pct"] >= PARAMS["min_advance_pct"]),
        Rule("decline bigger or longer than any reaction in the advance", lambda g: size_exceeded(g) or time_exceeded(g)),
    ],
)
