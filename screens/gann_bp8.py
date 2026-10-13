"""
Gann Buying Point #8 (Trading Methods of W.D. Gann, Appendix C).

A double, triple or higher bottom, then the first close above the top made
between the bottoms. Breakout volume is the institutional footprint check.
The setup stays listed while price holds above the second bottom, Gann's
natural stop for this buy.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "min_bars_between_bottoms": 5,
    "max_bars_between_bottoms": 60,
    "bottom_tolerance_pct": 2.0,      # second bottom may undercut the first by this much
    "min_top_above_bottom_pct": 5.0,  # the top between bottoms has to be a real rally
    "new_within_bars": 1,             # crossed this recently is NEW, older is ONGOING
    "max_days_listed": 20,            # drop it after this many days even if it still holds
    "min_breakout_rvol": 1.5,
}


def pattern(s, l2):
    earlier = [i for i in s.price_pivot_lows
               if PARAMS["min_bars_between_bottoms"] <= l2 - i <= PARAMS["max_bars_between_bottoms"]]
    if not earlier:
        return None
    l1 = min(earlier, key=lambda i: s.lows[i])
    top = s.highest_high(l1 + 1, l2 - 1)  # the top sits between the bottoms, not on them
    top_price = s.highs[top]
    cross = next((i for i in range(l2 + 1, s.last + 1) if s.closes[i] > top_price), None)
    rvol = None
    if cross is not None and cross >= 20:
        avg = sum(s.volumes[cross - 20:cross]) / 20
        rvol = s.volumes[cross] / avg if avg else None
    return {"l1": l1, "l2": l2, "top": top, "b1": s.lows[l1], "b2": s.lows[l2],
            "top_price": top_price, "cross": cross, "rvol": rvol}


def holds(x):
    return (x["b2"] >= x["b1"] * (1 - PARAMS["bottom_tolerance_pct"] / 100.0)
            and x["top_price"] >= x["b1"] * (1 + PARAMS["min_top_above_bottom_pct"] / 100.0))


def find(s):
    if not s.price_pivot_lows:
        return None
    # A pullback after the breakout makes a new pivot low, so look back past it for the
    # most recent bottom pattern that broke out within the listing window.
    for l2 in reversed(s.price_pivot_lows):
        if s.bars_ago(l2) > PARAMS["max_days_listed"] + PARAMS["max_bars_between_bottoms"]:
            break
        x = pattern(s, l2)
        if x and x["cross"] is not None and s.bars_ago(x["cross"]) <= PARAMS["max_days_listed"] and holds(x):
            return x
    return pattern(s, s.price_pivot_lows[-1])


def setup(g):
    return memo(g, "gann_bp8", find)


def bottoms_hold(g):
    x = setup(g)
    return x["b2"] >= x["b1"] * (1 - PARAMS["bottom_tolerance_pct"] / 100.0)


def real_top(g):
    x = setup(g)
    return x["top_price"] >= x["b1"] * (1 + PARAMS["min_top_above_bottom_pct"] / 100.0)


def recent_cross(g):
    x = setup(g)
    return x["cross"] is not None and g["structure"].bars_ago(x["cross"]) <= PARAMS["max_days_listed"]


def describe(g):
    x, s = setup(g), g["structure"]
    vol = f", breakout volume {x['rvol']:.1f}x normal" if x["rvol"] is not None else ""
    return (f"{listing_status(s, x['cross'], PARAMS['new_within_bars'])}. "
            f"bottoms {x['b1']:.2f} ({s.date(x['l1'])}) and {x['b2']:.2f} ({s.date(x['l2'])}), "
            f"top between {x['top_price']:.2f}, closed above it {s.date(x['cross'])}{vol}, last close {s.close:.2f}")


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
        "first (within 2%), with a rally of 5%+ between them. Price closed above that rally's top "
        "on at least 1.5x normal volume, and SPY is in an uptrend. It stays listed for up to 20 days "
        "while price holds above the second bottom. NEW on the breakout day, ONGOING after that."
    ),
    rules=[
        Rule("double or higher bottom", lambda g: setup(g) is not None and bottoms_hold(g)),
        Rule("rally of 5%+ between the bottoms", real_top),
        Rule("close above the top in the last 20 days", recent_cross),
        Rule("breakout volume 1.5x normal or more", lambda g: setup(g)["rvol"] >= PARAMS["min_breakout_rvol"]),
        Rule("no close below the second bottom since", lambda g: min(g["structure"].closes[setup(g)["cross"]:]) >= setup(g)["b2"]),
        Rule("SPY in an uptrend", market_ok),
    ],
)
