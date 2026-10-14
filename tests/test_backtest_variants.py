import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_variants  # noqa: E402
from screens import load_screens  # noqa: E402
from screens.base import SETUP, WATCHLIST  # noqa: E402
import test_watchlist_screens as tws  # noqa: E402

SCREENS = [sc for sc in load_screens() if sc.universe == WATCHLIST and sc.kind == SETUP]
VARIANTS = {v.id: v for v in backtest_variants.variants(SCREENS)}


class VariantTests(unittest.TestCase):
    def test_ids_are_unique_and_originals_untouched(self):
        self.assertEqual(len(VARIANTS), 5)
        self.assertFalse(set(VARIANTS) & {sc.id for sc in SCREENS})
        bp8 = next(sc for sc in SCREENS if sc.id == "gann_bp8")
        self.assertEqual(len(bp8.rules), 7)

    def bp8(self, extra_closes=()):
        g = tws.GannBp8Tests.build(None, 92, 2_000_000)
        closes = list(g["structure"].closes) + list(extra_closes)
        vols = list(g["structure"].volumes) + [1_000_000] * len(extra_closes)
        return tws.item(tws.bars_from_closes(closes, vols))

    def test_bp8_top_stop(self):
        v = VARIANTS["gann_bp8__top_stop"]
        g = self.bp8()
        self.assertEqual(v.failed_rules(g), [])
        from screens import gann_bp8
        self.assertEqual(v.trade(g)["stop"], gann_bp8.setup(g)["top_price"])
        self.assertEqual(v.trade(g)["key"], gann_bp8.trade(g)["key"])
        # Back under the old top: the original still lists it, the variant drops it.
        g = self.bp8([99.0])
        self.assertEqual(VARIANTS["gann_bp8__half_stop"].failed_rules(g), [])
        self.assertIn("no close below the old top since the breakout", v.failed_rules(g))

    def test_lf_new_only_and_reward(self):
        lows = {200: 90.0, 210: 95.0}
        new = VARIANTS["lost_forecasting__new_only"]
        self.assertEqual(new.failed_rules(tws.item(tws.shaped(212, lows=lows))), [])
        self.assertIn("listed the day L2 completes", new.failed_rules(tws.item(tws.shaped(214, lows=lows))))
        # Entry ~121.1 over a 95 stop is ~26 of risk against a target only ~2 above it.
        self.assertIn("target at least 2x the risk from the buy limit",
                      VARIANTS["lost_forecasting__reward_2r"].failed_rules(tws.item(tws.shaped(212, lows=lows))))


if __name__ == "__main__":
    unittest.main()
