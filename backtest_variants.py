"""
backtest_variants.py - backtest-only tweaks of the sheet screens, scored next to the originals.

The live screens follow their source material exactly. These variants exist only in the
backtest so a tweak can be judged before anyone changes a screen: each one is a copy of a
screen with an extra rule, a different stop, or both. A variant earns a change to the live
screen only if it clearly beats both the original and the baseline.
"""

from dataclasses import replace

from screens import gann_bp8, lost_forecasting
from screens.base import Rule


def _bp8_stop(level, label):
    """BP8 with a tighter stop at level(s, x); the setup drops on a close below it, like the original."""
    def holds(g):
        x, s = gann_bp8.setup(g), g["structure"]
        return x is not None and x["cross"] is not None and min(s.closes[x["cross"]:]) >= level(s, x)

    def trade(g):
        x, s = gann_bp8.setup(g), g["structure"]
        return {**gann_bp8.trade(g), "stop": level(s, x),
                "plan": f"stop: close below {label}, target a measured move above the top"}

    return [Rule(f"no close below {label} since the breakout", holds)], trade


def _lf_rule(label, check):
    def rule(g):
        x, s = lost_forecasting.setup(g), g["structure"]
        return x is not None and bool(check(s, x))
    return Rule(label, rule)


def _variant(sc, suffix, name, rules=(), trade=None):
    return replace(sc, id=f"{sc.id}__{suffix}", name=f"{sc.name} [variant: {name}]",
                   rules=list(sc.rules) + list(rules), trade=trade or sc.trade)


def variants(screens):
    """Variant screens for the originals in screens (missing originals are skipped)."""
    by_id = {sc.id: sc for sc in screens}
    out = []
    bp8 = by_id.get("gann_bp8")
    if bp8:
        rules, trade = _bp8_stop(lambda s, x: x["top_price"], "the old top")
        out.append(_variant(bp8, "top_stop", "stop at the old top", rules, trade))
        rules, trade = _bp8_stop(lambda s, x: (x["top_price"] + x["b2"]) / 2, "halfway back to the second bottom")
        out.append(_variant(bp8, "half_stop", "stop halfway to the second bottom", rules, trade))
    lf = by_id.get("lost_forecasting")
    if lf:
        out.append(_variant(lf, "above_200d", "close above the 200-day SMA", [_lf_rule(
            "close above the 200-day SMA", lambda s, x: s.sma_200 is not None and s.close > s.sma_200)]))
        out.append(_variant(lf, "new_only", "only on the day L2 completes", [_lf_rule(
            "listed the day L2 completes", lambda s, x: s.bars_ago(x["trigger"]) == 0)]))
        out.append(_variant(lf, "reward_2r", "target at least 2x the risk", [_lf_rule(
            "target at least 2x the risk from the buy limit",
            lambda s, x: x["entry"] > x["l2p"] and x["target"] - x["entry"] >= 2 * (x["entry"] - x["l2p"]))]))
    return out
