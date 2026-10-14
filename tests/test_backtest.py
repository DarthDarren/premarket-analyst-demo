import os
import random
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest  # noqa: E402
import daily_structure  # noqa: E402
from screens import load_screens  # noqa: E402
from screens.base import SETUP, WATCHLIST  # noqa: E402


def random_walk(n, seed, drift=0.0008):
    rng = random.Random(seed)
    dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(n)]
    closes, p = [], 50.0
    for _ in range(n):
        p *= 1 + drift + rng.gauss(0, 0.018)
        closes.append(p)
    opens = [c * (1 + rng.gauss(0, 0.004)) for c in closes]
    highs = [max(o, c) * (1 + abs(rng.gauss(0, 0.008))) for o, c in zip(opens, closes)]
    lows = [min(o, c) * (1 - abs(rng.gauss(0, 0.008))) for o, c in zip(opens, closes)]
    vols = [1e6 * (1 + abs(rng.gauss(0, 0.5))) for _ in range(n)]
    return daily_structure.build(dates, opens, highs, lows, closes, vols)


SCREENS = [sc for sc in load_screens() if sc.universe == WATCHLIST and sc.kind == SETUP]


class ViewTests(unittest.TestCase):
    def test_view_matches_a_fresh_build(self):
        full = random_walk(700, seed=1)
        for t in (320, 451, 699):
            v = backtest.view(full, t)
            lo = t - backtest.VIEW_BARS + 1
            b = daily_structure.build(full.dates[lo:t + 1], full.opens[lo:t + 1], full.highs[lo:t + 1],
                                      full.lows[lo:t + 1], full.closes[lo:t + 1], full.volumes[lo:t + 1])
            self.assertEqual(v.price_pivot_lows, b.price_pivot_lows)
            self.assertEqual(v.price_pivot_highs, b.price_pivot_highs)
            self.assertAlmostEqual(v.sma_50, b.sma_50)
            self.assertAlmostEqual(v.sma_200, b.sma_200)
            self.assertAlmostEqual(v.chop, b.chop)
            self.assertAlmostEqual(v.rvol, b.rvol)
            # RSI is causal, so the cut full-history values only differ from a fresh build by warmup.
            self.assertEqual(v.rsi, full.rsi[lo:t + 1])
            self.assertEqual(v.rsi_troughs, [i - lo for i in full.rsi_troughs if lo < i < t])
            self.assertEqual(v.rsi_peaks, [i - lo for i in full.rsi_peaks if lo < i < t])
            self.assertEqual(v.close, full.closes[t])

    def test_view_never_sees_future_bars(self):
        full = random_walk(500, seed=2)
        v = backtest.view(full, 400)
        self.assertEqual(v.dates[-1], full.dates[400])
        self.assertTrue(all(i < len(v.closes) - 1 for i in v.price_pivot_lows + v.rsi_troughs))


class SimulateTests(unittest.TestCase):
    def flat(self, n=40):
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
        return daily_structure.build(dates, [100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n, [1e6] * n)

    def test_wick_through_stop_is_only_the_sensitivity(self):
        s = self.flat()
        s.lows[5] = 90.0
        out = backtest.simulate(s, 2, stop=95.0, target=120.0)
        self.assertEqual(out["exit_reason"], "time")       # the screen would still list it
        self.assertAlmostEqual(out["return_wick_pct"], -5.0)

    def test_close_below_stop(self):
        s = self.flat()
        s.lows[5], s.closes[5] = 93.0, 94.0
        out = backtest.simulate(s, 2, stop=95.0, target=120.0)
        self.assertEqual((out["exit_reason"], out["exit_index"]), ("stop", 5))
        self.assertAlmostEqual(out["return_pct"], -6.0)
        self.assertAlmostEqual(out["r_multiple"], -1.2)

    def test_target_hit(self):
        s = self.flat()
        s.highs[6] = 111.0
        out = backtest.simulate(s, 2, stop=95.0, target=110.0)
        self.assertEqual(out["exit_reason"], "target")
        self.assertAlmostEqual(out["r_multiple"], 2.0)

    def test_time_exit_and_too_recent(self):
        s = self.flat()
        out = backtest.simulate(s, 2, stop=95.0, target=None)
        self.assertEqual((out["exit_reason"], out["days"]), ("time", backtest.HOLD_DAYS))
        self.assertIsNone(backtest.simulate(s, 30, stop=95.0, target=None))


class ReplayTests(unittest.TestCase):
    def test_every_setup_screen_has_a_trade(self):
        self.assertTrue(SCREENS)
        for sc in SCREENS:
            self.assertIsNotNone(sc.trade, sc.id)

    def test_one_trade_per_setup_through_an_spy_blip(self):
        full = random_walk(700, seed=5)
        spy_dates = full.dates
        rows = [{"ticker": "T", "tier": "core_candidate", "source_lists": [], "owned": False}]

        class Always:
            # A stand-in screen listing one fixed setup every day.
            id, tiers, describe = "always", (), None

            def passes(self, item):
                return item["market_regime"] == "uptrend"

            def trade(self, item):
                return {"stop": None, "target": None, "plan": "time", "key": ("same",)}

        regimes = {d: "uptrend" for d in spy_dates}
        regimes[spy_dates[400]] = "choppy"
        signals, _ = backtest.replay(rows, {"T": full}, regimes, [Always()], spy_dates[300])
        self.assertEqual(len(signals), 1)

    def test_replay_and_report_on_random_walks(self):
        structures = {f"T{i}": random_walk(900, seed=10 + i) for i in range(4)}
        structures["SPY"] = random_walk(900, seed=99, drift=0.001)
        regimes = backtest.regime_by_date(structures["SPY"])
        rows = [{"ticker": t, "tier": "core_candidate", "source_lists": [], "owned": False}
                for t in structures if t != "SPY"]
        start = structures["SPY"].dates[400]
        signals, baseline = backtest.replay(rows, structures, regimes, SCREENS, start)
        self.assertTrue(baseline[20])
        for s in signals:
            self.assertGreaterEqual(s["date"], str(start))
        scored, base = backtest.score(signals, baseline, SCREENS)
        self.assertEqual([r["id"] for r in scored], [sc.id for sc in SCREENS])
        md = backtest.report(scored, base, {"start": start, "end": structures["SPY"].dates[-1],
                                            "tickers": 4, "baseline_days": len(baseline[20])})
        self.assertIn("| Screen | Signals |", md)
        self.assertIn("Caveats", md)


if __name__ == "__main__":
    unittest.main()
