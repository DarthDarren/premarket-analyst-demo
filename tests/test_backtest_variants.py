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
        self.assertEqual(len(VARIANTS), 3)
        self.assertFalse(set(VARIANTS) & {sc.id for sc in SCREENS})
        lf = next(sc for sc in SCREENS if sc.id == "lost_forecasting")
        self.assertEqual(len(lf.rules), 4)

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
