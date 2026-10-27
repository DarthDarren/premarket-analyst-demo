import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_ema  # noqa: E402
import daily_structure  # noqa: E402
from backtest_ema import Rule  # noqa: E402


def bars(closes):
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    opens = [c + 0.5 for c in closes]           # distinct from closes so fills are easy to spot
    return daily_structure.build(dates, opens, [c + 1 for c in closes], [c - 1 for c in closes],
                                 closes, [1e6] * len(closes))


class EmaTests(unittest.TestCase):
    def test_ema_seeds_with_the_sma(self):
        e = backtest_ema.ema([1, 2, 3, 4], 3)
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 4 * 0.5 + 2.0 * 0.5)

    def test_sma(self):
        self.assertEqual(backtest_ema.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])


class TradeTests(unittest.TestCase):
    # Flat, a rise, then a drop: one cross up and one cross down.
    CLOSES = [100.0] * 20 + [101, 103, 106, 110, 115, 120] + [110, 100, 95, 95, 95]

    def run_rule(self, rule, closes=None, regimes=None):
        full = bars(closes or self.CLOSES)
        return backtest_ema.trades(rule, full, backtest_ema.indicators(full), regimes or {}, 0), full

    def test_buys_after_the_cross_up_and_sells_after_the_cross_down(self):
        out, full = self.run_rule(Rule("t", "t"))
        self.assertEqual(len(out), 1)
        tr = out[0]
        self.assertEqual(tr["date"], full.dates[21].isoformat())        # signal on bar 20, fill at 21's open
        self.assertEqual(tr["entry"], full.opens[21])
        self.assertEqual(tr["exit_date"], full.dates[28].isoformat())   # 100 < EMA on bar 27, out at 28's open
        self.assertAlmostEqual(tr["return_pct"], 100 * (full.opens[28] - full.opens[21]) / full.opens[21])

    def test_two_closes_rule_waits_one_more_day(self):
        out, full = self.run_rule(Rule("t", "t", exit_closes=2))
        self.assertEqual(out[0]["exit_date"], full.dates[29].isoformat())

    def test_spy_filter_blocks_entries_off_uptrend_days(self):
        full = bars(self.CLOSES)
        self.assertEqual(self.run_rule(Rule("t", "t", spy=True))[0], [])
        up = {d: "uptrend" for d in full.dates}
        self.assertEqual(len(self.run_rule(Rule("t", "t", spy=True), regimes=up)[0]), 1)

    def test_trend_filter_needs_the_200_day(self):
        self.assertEqual(self.run_rule(Rule("t", "t", trend=True))[0], [])

    def test_already_above_the_ema_waits_for_a_fresh_cross(self):
        rising = [100.0 + i for i in range(40)]
        full = bars(rising)
        out = backtest_ema.trades(Rule("t", "t"), full, backtest_ema.indicators(full), {}, 20)
        self.assertEqual(out, [])

    def test_trade_still_open_at_the_end_is_left_out(self):
        out, _ = self.run_rule(Rule("t", "t"), closes=[100.0] * 20 + [101, 103, 106, 110])
        self.assertEqual(out, [])


class ScoreTests(unittest.TestCase):
    def test_cost_comes_off_every_trade(self):
        done = [{"date": "2025-01-02", "days": 2, "return_pct": 1.0},
                {"date": "2025-02-03", "days": 3, "return_pct": -0.5}]
        r = backtest_ema.score(Rule("t", "t"), done, 0.1, 0.05, 50)
        self.assertAlmostEqual(r["expectancy"], 0.25)
        self.assertAlmostEqual(r["expectancy_net"], 0.15)
        self.assertAlmostEqual(r["per_day_net"], 0.3 / 5)
        self.assertAlmostEqual(r["in_market"], 10.0)
        self.assertEqual(r["verdict"], "not enough trades")


if __name__ == "__main__":
    unittest.main()
