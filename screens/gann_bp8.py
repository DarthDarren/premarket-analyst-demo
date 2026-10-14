"""
Gann Buying Point #8 (Trading Methods of W.D. Gann, Appendix C).

A double, triple or higher bottom, then the first close above the top made
between the bottoms. Breakout volume is the institutional footprint check.
The setup stays listed while price holds above the second bottom, Gann's
natural stop for this buy.
"""

from .base import EXPERIMENTAL, WATCHLIST, Rule, Screen, has, listing_status, market_ok, memo

PARAMS = {
    "tiers": ["core_owned", "core_candidate", "broad_candidate"],
    "min_bars_between_bottoms": 5,
    "max_bars_between_bottoms": 60,
    "bottom_tolerance_pct": 2.0,      # second bottom may undercut the first by this much
    "min_top_above_bottom_pct": 5.0,  # the top between bottoms has to be a real rally
    "max_days_listed": 20,            # drop it after this many days even if it still holds
    "search_bars": 120,               # how far back a second bottom can be and still have a recent breakout
    "min_breakout_rvol": 1.5,
}


def bottoms_hold(x):
    return x["b2"] >= x["b1"] * (1 - PARAMS["bottom_tolerance_pct"] / 100.0)


def real_top(x):
    return x["top_price"] >= x["b1"] * (1 + PARAMS["min_top_above_bottom_pct"] / 100.0)


def first_bottom(s, l2):
    """The latest earlier pivot low that pairs with l2 as a double or higher bottom, else the latest earlier pivot."""
    earlier = [i for i in s.price_pivot_lows
               if PARAMS["min_bars_between_bottoms"] <= l2 - i <= PARAMS["max_bars_between_bottoms"]]
    floor = 1 - PARAMS["bottom_tolerance_pct"] / 100.0
    for l1 in reversed(earlier):
        # A real double bottom: the second holds the first, and nothing in between undercut them.
        if s.lows[l2] >= s.lows[l1] * floor and min(s.lows[l1:l2 + 1]) >= s.lows[l1] * floor:
            return l1
    return earlier[-1] if earlier else None


def pattern(s, l2):
    l1 = first_bottom(s, l2)
    if l1 is None:
        return None
    top = s.highest_high(l1 + 1, l2 - 1)  # the top sits between the bottoms, not on them
    top_price = s.highs[top]
    cross = next((i for i in range(l2 + 1, s.last + 1) if s.closes[i] > top_price), None)
    rvol = None
    if cross is not None and cross >= 20:
        avg = sum(s.volumes[cross - 20:cross]) / 20
        rvol = s.volumes[cross] / avg if avg else None
    return {"l1": l1, "l2": l2, "top": top, "b1": s.lows[l1], "b2": s.lows[l2],
            "top_price": top_price, "cross": cross, "rvol": rvol}


def recent_cross(s, x):
    return x["cross"] is not None and s.bars_ago(x["cross"]) <= PARAMS["max_days_listed"]


def volume_ok(x):
    return x["rvol"] is not None and x["rvol"] >= PARAMS["min_breakout_rvol"]


def holds_b2(s, x):
    return x["cross"] is not None and min(s.closes[x["cross"]:]) >= x["b2"]


def measured_move(x):
    return x["top_price"] + (x["top_price"] - x["b2"])


def target_open(s, x):
    # Once price has reached the measured move the breakout has played out; don't keep listing it.
    return x["cross"] is not None and max(s.highs[x["cross"]:]) < measured_move(x)


def find(s):
    """Newest bottom pair that broke out within the listing window and still holds; else the newest pair."""
    newest = None
    for l2 in reversed(s.price_pivot_lows):
        if s.bars_ago(l2) > PARAMS["search_bars"]:
            break
        x = pattern(s, l2)
        if x is None:
            continue
        newest = newest or x
        if bottoms_hold(x) and real_top(x) and recent_cross(s, x) and volume_ok(x) and holds_b2(s, x) and target_open(s, x):
            return x
    return newest


def setup(g):
    return memo(g, "gann_bp8", find)


def describe(g):
    x, s = setup(g), g["structure"]
    vol = f", breakout volume {x['rvol']:.1f}x normal" if x["rvol"] is not None else ""
    return (f"{listing_status(s, x['cross'])}. "
            f"bottoms {x['b1']:.2f} ({s.date(x['l1'])}) and {x['b2']:.2f} ({s.date(x['l2'])}), "
            f"top between {x['top_price']:.2f}, closed above it {s.date(x['cross'])}{vol}, last close {s.close:.2f}")


def trade(g):
    x, s = setup(g), g["structure"]
    return {"stop": x["b2"], "target": measured_move(x),
            "plan": "stop: close below the second bottom, target a measured move above the top",
            "key": (s.date(x["l1"]), s.date(x["l2"]))}


SCREEN = Screen(
    id="gann_bp8",
    name="Gann Buying Point #8, higher bottom breakout",
    status=EXPERIMENTAL,
    universe=WATCHLIST,
    tiers=tuple(PARAMS["tiers"]),
    order=43,
    params=PARAMS,
    describe=describe,
    trade=trade,
    criteria=(
        "Watchlist chart setup. Two pivot bottoms 5 to 60 days apart, the second at or above the "
        "first (within 2%) with nothing lower in between, and a rally of 5%+ between them. Price closed "
        "above that rally's top on at least 1.5x normal volume, and SPY is in an uptrend. It stays listed "
        "for up to 20 days while price holds above the second bottom and hasn't reached the measured move (the top plus "
        "its height above the second bottom). NEW on the breakout day, ONGOING after that."
    ),
    rules=[
        Rule("double or higher bottom", lambda g: has(g, setup, bottoms_hold)),
        Rule("rally of 5%+ between the bottoms", lambda g: has(g, setup, real_top)),
        Rule("close above the top in the last 20 days", lambda g: has(g, setup, lambda x: recent_cross(g["structure"], x))),
        Rule("breakout volume 1.5x normal or more", lambda g: has(g, setup, volume_ok)),
        Rule("no close below the second bottom since", lambda g: has(g, setup, lambda x: holds_b2(g["structure"], x))),
        Rule("measured-move target not reached yet", lambda g: has(g, setup, lambda x: target_open(g["structure"], x))),
        Rule("SPY in an uptrend", market_ok),
    ],
)
