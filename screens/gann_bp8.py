"""
Gann Buying Point #8 (Trading Methods of W.D. Gann, Appendix C).

A double, triple or higher bottom, then the first close above the top made
between the bottoms. Breakout volume is the institutional footprint check.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, market_ok, memo

PARAMS = {
    "tiers": ["core_candidate", "broad_candidate"],
    "min_bars_between_bottoms": 5,
    "max_bars_between_bottoms": 60,
    "bottom_tolerance_pct": 2.0,      # second bottom may undercut the first by this much
    "min_top_above_bottom_pct": 5.0,  # the top between bottoms has to be a real rally
    "max_bars_since_cross": 1,        # 0 = crossed on the last finished day
    "min_breakout_rvol": 1.5,
}


def find(s):
    if not s.price_pivot_lows:
        return None
    l2 = s.price_pivot_lows[-1]
    earlier = [i for i in s.price_pivot_lows
               if PARAMS["min_bars_between_bottoms"] <= l2 - i <= PARAMS["max_bars_between_bottoms"]]
    if not earlier:
        return None
    l1 = min(earlier, key=lambda i: s.lows[i])
    top = s.highest_high(l1, l2)
    top_price = s.highs[top]
    cross = next((i for i in range(l2 + 1, s.last + 1) if s.closes[i] > top_price), None)
    rvol = None
    if cross is not None and cross >= 20:
        avg = sum(s.volumes[cross - 20:cross]) / 20
        rvol = s.volumes[cross] / avg if avg else None
    return {"l1": l1, "l2": l2, "top": top, "b1": s.lows[l1], "b2": s.lows[l2],
            "top_price": top_price, "cross": cross, "rvol": rvol}


def setup(g):
    return memo(g, "gann_bp8", find)


def bottoms_hold(g):
    x = setup(g)
    return x["b2"] >= x["b1"] * (1 - PARAMS["bottom_tolerance_pct"] / 100.0)


def real_top(g):
    x = setup(g)
    return x["top_price"] >= x["b1"] * (1 + PARAMS["min_top_above_bottom_pct"] / 100.0)


def fresh_cross(g):
    x = setup(g)
    return x["cross"] is not None and g["structure"].bars_ago(x["cross"]) <= PARAMS["max_bars_since_cross"]


def describe(g):
    x, s = setup(g), g["structure"]
    vol = f", breakout volume {x['rvol']:.1f}x normal" if x["rvol"] is not None else ""
    return (f"bottoms {x['b1']:.2f} ({s.date(x['l1'])}) and {x['b2']:.2f} ({s.date(x['l2'])}), "
            f"top between {x['top_price']:.2f}, closed above it {s.date(x['cross'])}{vol}")


SCREEN = Screen(
    id="gann_bp8",
    name="Gann Buying Point #8, higher bottom breakout",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=43,
    params=PARAMS,
    describe=describe,
    criteria=(
        "Watchlist chart setup. Two pivot bottoms 5 to 60 days apart, the second at or above the "
        "first (within 2%), with a rally of 5%+ between them. Price just made its first close "
        "above that rally's top, on at least 1.5x normal volume, and SPY is in an uptrend."
    ),
    rules=[
        Rule("double or higher bottom", lambda g: setup(g) is not None and bottoms_hold(g)),
        Rule("rally of 5%+ between the bottoms", real_top),
        Rule("first close above the top, last 2 days", fresh_cross),
        Rule("breakout volume 1.5x normal or more", lambda g: setup(g)["rvol"] >= PARAMS["min_breakout_rvol"]),
        Rule("SPY in an uptrend", market_ok),
    ],
)
