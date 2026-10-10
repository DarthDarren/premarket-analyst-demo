"""
Offline checks for daily_structure and the watchlist Lab screens, on made-up
bars shaped like each setup. Run: python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daily_structure  # noqa: E402
import watchlist_universe  # noqa: E402
from screens import (  # noqa: E402
    gann_bp7, gann_bp8, gann_selling_points, lost_forecasting, rsi_bear_resistance_divergence,
    rsi_bull_support_divergence,
)


def bars_from_closes(closes, volumes=None, wick=0.5):
    """Bars whose highs and lows sit a fixed wick around each close."""
    n = len(closes)
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]
    highs = [c + wick for c in closes]
    lows = [c - wick for c in closes]
    volumes = volumes or [1_000_000] * n
    return daily_structure.build(dates, closes, highs, lows, closes, volumes)


def ramp(start, end, steps):
    return [start + (end - start) * i / steps for i in range(1, steps + 1)]


def item(s, regime="uptrend"):
    return {"ticker": "TEST", "tier": "core_candidate", "source_lists": ["Blue"], "owned": False,
            "structure": s, "market_regime": regime}


def uptrend_base(n=220):
    # Steady climb with small zigzags so SMAs stack and RSI lives in a bull range.
    out, p = [], 50.0
    for i in range(n):
        p += 0.25 if i % 4 else -0.4
        out.append(p)
    return out


class StructureTests(unittest.TestCase):
    def test_rsi_bounds_and_flat(self):
        s = bars_from_closes(uptrend_base())
        vals = [r for r in s.rsi if r is not None]
        self.assertTrue(all(0 <= r <= 100 for r in vals))
        self.assertEqual(daily_structure.wilder_rsi([1.0] * 5), [None] * 5)

    def test_pivots_need_both_sides(self):
        self.assertEqual(daily_structure.pivot_lows([5, 3, 4, 2]), [1])
        self.assertEqual(daily_structure.pivot_highs([1, 3, 2, 4]), [1])

    def test_regime(self):
        self.assertEqual(daily_structure.regime(bars_from_closes(ramp(50, 150, 260)))["state"], "uptrend")
        self.assertEqual(daily_structure.regime(bars_from_closes(ramp(150, 50, 260)))["state"], "downtrend")
        chop = [100 + (3 if i % 2 else -3) for i in range(260)]
        self.assertEqual(daily_structure.regime(bars_from_closes(chop))["state"], "choppy")
        self.assertEqual(daily_structure.regime(None)["state"], "unknown")


class LostForecastingTests(unittest.TestCase):
    def series(self, l2_price):
        base = uptrend_base()
        p = base[-1]
        # L1, rally to a cycle high, pull back to L2, then one confirming bar.
        tail = ramp(p, p - 6, 6) + ramp(p - 6, p + 4, 8) + ramp(p + 4, l2_price, 6) + [l2_price + 1.5]
        return base + tail, p - 6

    def test_fires_on_fresh_higher_low(self):
        _, l1 = self.series(0)
        closes, _ = self.series(l2_price=l1 + 3)
        g = item(bars_from_closes(closes))
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        self.assertIn("higher low L2", lost_forecasting.describe(g))

    def test_lower_low_does_not_fire(self):
        _, l1 = self.series(0)
        closes, _ = self.series(l2_price=l1 - 2)
        g = item(bars_from_closes(closes))
        self.assertIn("fresh higher low (L2 above L1) just confirmed", lost_forecasting.SCREEN.failed_rules(g))

    def test_market_filter(self):
        _, l1 = self.series(0)
        closes, _ = self.series(l2_price=l1 + 3)
        g = item(bars_from_closes(closes), regime="choppy")
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), ["SPY in an uptrend"])


class RsiDivergenceTests(unittest.TestCase):
    def test_fires_on_divergence_in_bull_support(self):
        closes = uptrend_base(200)
        p = closes[-1]
        # Run up, sharp drop (first RSI trough), bounce, then a slow zigzag to a slightly
        # lower price low that RSI doesn't confirm, then one confirming up day.
        closes += ramp(p, p + 10, 10) + ramp(p + 10, p - 1, 2) + ramp(p - 1, p + 4, 5)
        q = closes[-1]
        for i in range(30):
            q += -0.9 if i % 2 == 0 else 0.6
            closes.append(q)
        closes.append(q + 1.2)
        g = item(bars_from_closes(closes, wick=0.2))
        self.assertEqual(rsi_bull_support_divergence.SCREEN.failed_rules(g), [], rsi_bull_support_divergence.setup(g))
        self.assertIn("higher low in RSI", rsi_bull_support_divergence.describe(g))

    def test_no_divergence_when_rsi_lower_too(self):
        closes = uptrend_base(200)
        p = closes[-1]
        closes += ramp(p, p + 10, 10) + ramp(p + 10, p - 1, 4) + ramp(p - 1, p + 4, 5) + ramp(p + 4, p - 4, 3) + [p - 2]
        g = item(bars_from_closes(closes, wick=0.2))
        self.assertIn("lower price low with higher RSI low", rsi_bull_support_divergence.SCREEN.failed_rules(g))


class GannBp7Tests(unittest.TestCase):
    def test_fires_at_half_retracement(self):
        closes = [100.0] * 100 + ramp(100, 140, 60) + ramp(140, 120.5, 8) + [121.5]
        g = item(bars_from_closes(closes))
        failed = gann_bp7.SCREEN.failed_rules(g)
        self.assertNotIn("pullback reached the 50% level", failed)
        self.assertNotIn("no close below the 50% level", failed)
        self.assertNotIn("advance of 15%+ into the high", failed)

    def test_shallow_pullback_does_not_fire(self):
        closes = [100.0] * 100 + ramp(100, 140, 60) + ramp(140, 135, 8)
        g = item(bars_from_closes(closes))
        self.assertIn("pullback reached the 50% level", gann_bp7.SCREEN.failed_rules(g))


class GannBp8Tests(unittest.TestCase):
    def build(self, second_bottom, breakout_volume):
        closes = [100.0] * 60 + ramp(100, 90, 5) + ramp(90, 100, 8) + ramp(100, second_bottom, 8) + ramp(second_bottom, 99.5, 6)
        closes.append(102.0)  # first close above the top between the bottoms
        vols = [1_000_000] * (len(closes) - 1) + [breakout_volume]
        return item(bars_from_closes(closes, vols))

    def test_fires_on_higher_bottom_breakout(self):
        g = self.build(92, 2_000_000)
        self.assertEqual(gann_bp8.SCREEN.failed_rules(g), [], gann_bp8.setup(g))

    def test_needs_volume(self):
        g = self.build(92, 1_000_000)
        self.assertEqual(gann_bp8.SCREEN.failed_rules(g), ["breakout volume 1.5x normal or more"])

    def test_lower_bottom_does_not_fire(self):
        g = self.build(85, 2_000_000)
        self.assertIn("double or higher bottom", gann_bp8.SCREEN.failed_rules(g))


class GannSellingPointsTests(unittest.TestCase):
    def advance(self):
        # Flat base, then a stair-step advance whose reactions are 3 small down days each.
        closes, p = [100.0] * 100, 100.0
        for _ in range(12):
            for _ in range(4):
                p += 1.2
                closes.append(p)
            for _ in range(3):
                p -= 0.5
                closes.append(p)
        for _ in range(4):
            p += 1.2
            closes.append(p)
        return closes, p

    def test_fires_when_decline_beats_biggest_reaction(self):
        closes, top = self.advance()
        g = item(bars_from_closes(closes + ramp(top, top * 0.85, 10)), regime="downtrend")
        self.assertEqual(gann_selling_points.SCREEN.failed_rules(g), [])
        self.assertIn("#4 size", gann_selling_points.describe(g))
        self.assertIn("#6 time", gann_selling_points.describe(g))

    def test_small_short_dip_does_not_fire(self):
        closes, top = self.advance()
        g = item(bars_from_closes(closes + [top - 0.3, top - 0.1]))
        self.assertEqual(gann_selling_points.SCREEN.failed_rules(g),
                         ["decline bigger or longer than any reaction in the advance"])


class RsiBearDivergenceTests(unittest.TestCase):
    def build(self, grind_steps):
        closes = [50.0 + (0.3 if i % 2 else 0) for i in range(60)]
        p = closes[-1]
        # Strong run (RSI into the 80s), pullback, slow grind to a higher high, then a down day.
        for i in range(16):
            p += 1.5 if i % 3 else -0.3
            closes.append(p)
        closes += ramp(p, p - 4, 4)
        q = closes[-1]
        for i in range(grind_steps):
            q += 0.8 if i % 2 == 0 else -0.35
            closes.append(q)
        closes.append(q - 2)
        return item(bars_from_closes(closes, wick=0.2))

    def test_fires_on_higher_high_lower_rsi(self):
        g = self.build(20)
        self.assertEqual(rsi_bear_resistance_divergence.SCREEN.failed_rules(g), [], rsi_bear_resistance_divergence.setup(g))
        self.assertIn("lower high in RSI", rsi_bear_resistance_divergence.describe(g))

    def test_no_alert_without_a_higher_price_high(self):
        g = self.build(16)
        self.assertEqual(rsi_bear_resistance_divergence.SCREEN.failed_rules(g), ["higher price high with lower RSI high"])


class UniverseTests(unittest.TestCase):
    def test_reads_newest_csv_and_caches(self):
        with tempfile.TemporaryDirectory() as d:
            header = "ticker,exchange,symbol,source_lists,list_count,suggested_tier,owned,flags\n"
            with open(os.path.join(d, "watchlist_merged_20260101_000000.csv"), "w") as f:
                f.write(header + "NASDAQ:OLD,NASDAQ,OLD,Blue,1,core_candidate,,\n")
            with open(os.path.join(d, "watchlist_merged_20260201_000000.csv"), "w") as f:
                f.write(header + "NYSE:BRK.B,NYSE,BRK.B,Blue;Red,2,core_candidate,,\n"
                        "TSX:SHOP,TSX,SHOP,Blue,1,exclude,,\n"
                        "NASDAQ:KLAC,NASDAQ,KLAC,Blue,1,core_owned,Y,held_in:x\n")
            cache = os.path.join(d, "cache.json")
            old_env, old_cache = os.environ.get("PREMARKET_WATCHLIST_DIR"), watchlist_universe.CACHE_PATH
            os.environ["PREMARKET_WATCHLIST_DIR"] = d
            watchlist_universe.CACHE_PATH = cache
            try:
                rows, info = watchlist_universe.load(log=lambda m: None)
                self.assertEqual([r["ticker"] for r in rows], ["BRK-B", "KLAC"])
                self.assertTrue(rows[1]["owned"])
                self.assertEqual(info["source_file"], "watchlist_merged_20260201_000000.csv")
                os.environ["PREMARKET_WATCHLIST_DIR"] = os.path.join(d, "missing")
                rows, info = watchlist_universe.load(log=lambda m: None)
                self.assertEqual(info["loaded_from"], "cache")
                self.assertEqual(len(rows), 2)
            finally:
                watchlist_universe.CACHE_PATH = old_cache
                if old_env is None:
                    os.environ.pop("PREMARKET_WATCHLIST_DIR", None)
                else:
                    os.environ["PREMARKET_WATCHLIST_DIR"] = old_env


if __name__ == "__main__":
    unittest.main()


class ScanWiringTests(unittest.TestCase):
    def test_run_watchlist_screens_with_fake_download(self):
        import json
        import random

        import pandas as pd

        import scan

        def fake_download(tickers, **kwargs):
            frames = {}
            idx = pd.date_range("2024-06-01", periods=400, freq="B", tz="America/New_York")
            for t in tickers:
                rnd = random.Random(t)
                p, rows = 50.0, []
                for _ in idx:
                    p *= 1 + rnd.uniform(-0.03, 0.032)
                    rows.append((p, p * 1.01, p * 0.99, p, rnd.randint(5, 20) * 100_000))
                frames[t] = pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"])
            return pd.concat(frames, axis=1)

        with tempfile.TemporaryDirectory() as d:
            header = "ticker,exchange,symbol,source_lists,list_count,suggested_tier,owned,flags\n"
            body = "".join(f"NASDAQ:T{i},NASDAQ,T{i},Blue,1,{'core_candidate' if i % 2 else 'broad_candidate'},,\n" for i in range(150))
            with open(os.path.join(d, "watchlist_merged_20261009_000000.csv"), "w") as f:
                f.write(header + body + "NASDAQ:OWN,NASDAQ,OWN,Blue,1,core_owned,Y,\n")
            old_dl, old_cache = scan.yf.download, watchlist_universe.CACHE_PATH
            os.environ["PREMARKET_WATCHLIST_DIR"] = d
            watchlist_universe.CACHE_PATH = os.path.join(d, "cache.json")
            scan.yf.download = fake_download
            try:
                regime, info, blocks = scan.run_watchlist_screens()
            finally:
                scan.yf.download = old_dl
                watchlist_universe.CACHE_PATH = old_cache
                os.environ.pop("PREMARKET_WATCHLIST_DIR", None)

        self.assertIn(regime["state"], ("uptrend", "downtrend", "choppy"))
        self.assertEqual(info["with_daily_bars"], 151)
        self.assertEqual(set(blocks), {"lost_forecasting", "rsi_bull_support_divergence", "gann_bp7", "gann_bp8",
                                       "gann_selling_points", "rsi_bear_resistance_divergence"})
        for block in blocks.values():
            self.assertEqual(block["scanned"], 1 if block["kind"] == "alert" else 150)
            self.assertLessEqual(len(block["hits"]), 8)
            self.assertEqual(set(block["hits"]), set(block["hit_details"]))
        json.dumps(blocks)  # packet has to serialize


class CycleHighBetweenLowsTest(unittest.TestCase):
    def test_wide_range_bar_at_l1_is_not_the_cycle_high(self):
        # L1's own bar has a tall upper wick; the cycle high must come from bars after it.
        closes = uptrend_base()
        p = closes[-1]
        closes += ramp(p, p - 6, 6) + ramp(p - 6, p + 4, 8) + ramp(p + 4, p - 3, 6) + [p - 1.5]
        s = bars_from_closes(closes)
        l1 = s.price_pivot_lows[-2]
        s.highs[l1] = p + 20
        x = lost_forecasting.find(s)
        self.assertGreater(x["h"], x["l1"])
        self.assertLess(x["h"], x["l2"])
