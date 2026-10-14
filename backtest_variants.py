"""
backtest_variants.py - backtest-only tweaks of the sheet screens, scored next to the originals.

The live screens follow their source material exactly. These variants exist only in the
backtest so a tweak can be judged before anyone changes a screen: each one is a copy of a
screen with an extra rule. A variant earns a change to the live screen only if it clearly
beats both the original and the baseline. (The Gann BP8 stop variants did, and BP8 now uses
the old-top stop itself.)
"""

from dataclasses import replace

from screens import lost_forecasting
from screens.base import Rule


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
