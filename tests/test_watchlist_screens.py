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
    rsi_bull_bear_support_divergence, rsi_bull_support_divergence,
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


def shaped(n, lows=None, highs=None, closes=None, rsi=None):
    """A steadily rising series with no pivots of its own, plus the exact lows, highs, closes and
    RSI values a test needs. RSI pivots are recomputed from the given RSI."""
    c = [100.0 + 0.1 * i for i in range(n)]
    for i, v in (closes or {}).items():
        c[i] = v
    h = [x + 0.5 for x in c]
    lo = [x - 0.5 for x in c]
    for i, v in (lows or {}).items():
        lo[i] = v
    for i, v in (highs or {}).items():
        h[i] = v
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]
    s = daily_structure.build(dates, c, h, lo, c, [1_000_000] * n)
    if rsi is not None:
        r = [60.0 + 0.001 * i for i in range(n)]
        for i, v in rsi.items():
            r[i] = v
        s.rsi = r
        s.rsi_troughs = daily_structure.pivot_lows(r)
        s.rsi_peaks = daily_structure.pivot_highs(r)
    return s


class LostForecastingTests(unittest.TestCase):
    # L1 at bar 200 (low 90), L2 at bar 210 (low 95), completed by bar 211.
    LOWS = {200: 90.0, 210: 95.0}

    def test_fires_with_entry_stop_and_both_targets(self):
        s = shaped(212, lows=self.LOWS)
        g = item(s)
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        x = lost_forecasting.setup(g)
        self.assertEqual((x["l1"], x["l2"]), (200, 210))
        self.assertAlmostEqual(x["target"], x["hp"] + 5.0)
        self.assertEqual(x["time_target"], x["h"] + 10)
        t = lost_forecasting.trade(g)
        self.assertEqual((t["entry"], t["stop"], t["entry_date"]), (s.closes[211], 95.0, s.date(211)))
        self.assertTrue(lost_forecasting.describe(g).startswith("NEW"))
        self.assertIn("time target about", lost_forecasting.describe(g))

    def test_lower_low_is_not_a_bullish_upside_cycle(self):
        g = item(shaped(212, lows={200: 90.0, 210: 85.0}))
        self.assertIn("cycle with a higher low (L2 above L1)", lost_forecasting.SCREEN.failed_rules(g))

    def test_market_gate(self):
        g = item(shaped(212, lows=self.LOWS), regime="choppy")
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), ["SPY in an uptrend (app market gate)"])

    def test_no_20_day_expiry(self):
        g = item(shaped(236, lows=self.LOWS))  # 25 bars after L2 completed, target still ahead
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        self.assertTrue(lost_forecasting.describe(g).startswith("ONGOING since"))

    def test_newer_pivot_that_is_no_valid_cycle_keeps_the_original(self):
        # A later 3-bar low under L2's low (but no close under it) forms no valid cycle of its own.
        g = item(shaped(220, lows={**self.LOWS, 215: 94.0}))
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        self.assertEqual(lost_forecasting.setup(g)["l2"], 210)

    def test_close_equal_to_l2_holds_close_below_voids(self):
        g = item(shaped(216, lows={**self.LOWS, 213: 94.5}, closes={213: 95.0}))
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        g = item(shaped(216, lows={**self.LOWS, 213: 94.5}, closes={213: 94.9}))
        self.assertNotEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        x = lost_forecasting.find(g["structure"])
        self.assertFalse(x["l2"] == 210 and lost_forecasting.holds_l2(g["structure"], x))

    def test_l1_is_the_nearest_prior_low(self):
        # Lows 90, 100, then 95 two bars later: 95 vs its nearest prior low (100) is no higher low, so it
        # must not pair with 90. The live cycle is 90 -> 100.
        g = item(shaped(216, lows={200: 90.0, 210: 100.0, 212: 95.0}))
        self.assertEqual(lost_forecasting.SCREEN.failed_rules(g), [])
        x = lost_forecasting.setup(g)
        self.assertEqual((x["l1"], x["l2"], x["l2p"]), (200, 210, 100.0))

    def test_cycle_longer_than_60_bars_is_rejected(self):
        s = shaped(240, lows={150: 90.0, 220: 95.0})
        self.assertIsNone(lost_forecasting.cycle(s, s.price_pivot_lows.index(220)))


class RsiDivergenceTests(unittest.TestCase):
    # RSI visits 85 at bar 200. Troughs: 212 (RSI 35, low 90), 220 (RSI 41, low 105), 230 (RSI 45, low 103).
    # The new trough diverges from the adjacent one (220) but not from the older, deeper one (212).
    RSI = {200: 85.0, 212: 35.0, 220: 41.0, 230: 45.0}
    LOWS = {212: 90.0, 220: 105.0, 230: 103.0}

    def build(self, n=232, rsi=None, lows=None, closes=None):
        return item(shaped(n, lows={**self.LOWS, **(lows or {})}, closes=closes, rsi={**self.RSI, **(rsi or {})}))

    def test_partner_is_the_adjacent_trough(self):
        g = self.build()
        self.assertEqual(rsi_bull_support_divergence.SCREEN.failed_rules(g), [], rsi_bull_support_divergence.setup(g))
        x = rsi_bull_support_divergence.setup(g)
        self.assertEqual((x["t1"], x["t2"]), (220, 230))
        self.assertIn("higher low in RSI", rsi_bull_support_divergence.describe(g))

    def test_entry_stop_and_2r_target_come_from_the_completing_candle(self):
        g = self.build()
        s, t = g["structure"], rsi_bull_support_divergence.trade(g)
        self.assertEqual((t["entry"], t["stop"]), (s.closes[231], s.lows[231]))
        self.assertAlmostEqual(t["target"], t["entry"] + 2 * (t["entry"] - t["stop"]))
        self.assertEqual(t["entry_date"], s.date(231))

    def test_needs_a_visit_to_bull_resistance(self):
        g = self.build(rsi={200: 75.0})
        self.assertIn("RSI visited Bull Resistance 80+ before the trough", rsi_bull_support_divergence.SCREEN.failed_rules(g))

    def test_no_divergence_when_rsi_lower_too(self):
        g = self.build(rsi={230: 40.0})
        self.assertIn("bullish divergence: higher RSI trough, lower price low", rsi_bull_support_divergence.SCREEN.failed_rules(g))

    def test_a_later_plain_trough_does_not_replace_it(self):
        g = self.build(n=245, rsi={240: 50.0}, lows={231: 120.0})  # wider stop keeps the 2R target out of reach
        self.assertEqual(rsi_bull_support_divergence.SCREEN.failed_rules(g), [], rsi_bull_support_divergence.setup(g))
        self.assertEqual(rsi_bull_support_divergence.setup(g)["t2"], 230)
        self.assertTrue(rsi_bull_support_divergence.describe(g).startswith("ONGOING since"))

    def test_close_below_the_stop_drops_it(self):
        g = self.build(n=240, lows={231: 120.0, 235: 110.0}, closes={235: 119.5})
        self.assertIn("no close below the stop since", rsi_bull_support_divergence.SCREEN.failed_rules(g))

    def test_only_the_previous_trough_counts(self):
        # RSI 42 at low 100, then 48 at low 90, then 45 at low 95: 45 is not higher than 48, so the
        # newest trough has no divergence, even though it would diverge from the older 42.
        g = self.build(rsi={212: 42.0, 220: 48.0, 230: 45.0}, lows={212: 100.0, 220: 90.0, 230: 95.0})
        s = g["structure"]
        self.assertIsNone(rsi_bull_support_divergence.partner(s, s.rsi_troughs.index(230)))
        self.assertNotEqual(rsi_bull_support_divergence.setup(g)["t2"], 230)

    def test_a_later_out_of_zone_divergence_does_not_hide_a_live_one(self):
        # Trough at 240: RSI 55 (above Bull Support) with a lower low than 230, a divergence outside the zone.
        g = self.build(n=245, rsi={240: 55.0}, lows={231: 120.0, 240: 100.0})
        self.assertEqual(rsi_bull_support_divergence.SCREEN.failed_rules(g), [], rsi_bull_support_divergence.setup(g))
        self.assertEqual(rsi_bull_support_divergence.setup(g)["t2"], 230)


class RsiBearSupportDivergenceTests(unittest.TestCase):
    # Troughs: 220 (RSI 22, low 105) and 230 (RSI 27, low 103): a higher RSI trough in Bear Support at a lower low.
    # No visit to 80+ is needed, unlike the Bull Support setup.
    RSI = {220: 22.0, 230: 27.0}
    LOWS = {220: 105.0, 230: 103.0}
    sc = rsi_bull_bear_support_divergence

    def build(self, n=232, rsi=None, lows=None, regime="uptrend"):
        return item(shaped(n, lows={**self.LOWS, **(lows or {})}, rsi={**self.RSI, **(rsi or {})}), regime)

    def test_fires_in_bear_support(self):
        g = self.build()
        self.assertEqual(self.sc.SCREEN.failed_rules(g), [], self.sc.setup(g))
        x, s, t = self.sc.setup(g), g["structure"], self.sc.trade(g)
        self.assertEqual((x["t1"], x["t2"]), (220, 230))
        self.assertEqual((t["entry"], t["stop"]), (s.closes[231], s.lows[231]))
        self.assertIn("in Bear Support", self.sc.describe(g))

    def test_bull_support_trough_is_not_bear_support(self):
        g = self.build(rsi={220: 38.0, 230: 44.0})
        self.assertIn("new trough inside Bear Support 20-30", self.sc.SCREEN.failed_rules(g))

    def test_no_divergence_when_rsi_lower_too(self):
        g = self.build(rsi={230: 21.0})
        self.assertIn("bullish divergence: higher RSI trough, lower price low", self.sc.SCREEN.failed_rules(g))

    def test_waits_on_spy(self):
        g = self.build(regime="choppy")
        self.assertEqual(self.sc.SCREEN.failed_rules(g), ["SPY in an uptrend (app market gate)"])


class GannBp7Tests(unittest.TestCase):
    def test_fires_at_half_retracement(self):
        # Long enough history for a real 200-day SMA, so the main-trend rule is tested too.
        closes = ramp(70, 100, 100) + [100.0] * 60 + ramp(100, 140, 60) + ramp(140, 120.5, 8) + [121.5]
        g = item(bars_from_closes(closes))
        self.assertEqual(gann_bp7.SCREEN.failed_rules(g), [], gann_bp7.setup(g))
        t = gann_bp7.trade(g)
        self.assertAlmostEqual(t["stop"], gann_bp7.setup(g)["half"] - gann_bp7.setup(g)["tol"])
        self.assertAlmostEqual(t["target"], 140.5)

    def test_shallow_pullback_does_not_fire(self):
        closes = [100.0] * 100 + ramp(100, 140, 60) + ramp(140, 135, 8)
        g = item(bars_from_closes(closes))
        self.assertIn("pullback reached the 50% level in the last 20 days", gann_bp7.SCREEN.failed_rules(g))

    def test_stays_listed_while_50_percent_holds(self):
        closes = [100.0] * 100 + ramp(100, 140, 60) + ramp(140, 120.5, 8) + [121.5] + ramp(121.5, 126, 6)
        g = item(bars_from_closes(closes))
        self.assertNotIn("pullback reached the 50% level in the last 20 days", gann_bp7.SCREEN.failed_rules(g))
        self.assertTrue(gann_bp7.describe(g).startswith("ONGOING since"))


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

    def test_stays_listed_through_a_pullback_that_holds_the_top(self):
        g = self.build(92, 2_000_000)
        closes = list(g["structure"].closes) + [104.0, 101.0, 100.5, 101.5, 103.0]   # top is 100.5
        vols = list(g["structure"].volumes) + [1_000_000] * 5
        g = item(bars_from_closes(closes, vols))
        self.assertEqual(gann_bp8.SCREEN.failed_rules(g), [], gann_bp8.setup(g))
        self.assertTrue(gann_bp8.describe(g).startswith("ONGOING since"))

    def test_pairs_the_adjacent_bottom_not_the_lowest(self):
        # An older, deeper low 40 days before a clean double bottom must not become the first bottom.
        closes = [100.0] * 30 + ramp(100, 80, 5) + ramp(80, 100, 20) + [100.0] * 5 + ramp(100, 90, 5) + ramp(90, 100, 8) \
            + ramp(100, 92, 8) + ramp(92, 99.5, 6) + [102.0]
        vols = [1_000_000] * (len(closes) - 1) + [2_000_000]
        g = item(bars_from_closes(closes, vols))
        self.assertEqual(gann_bp8.SCREEN.failed_rules(g), [], gann_bp8.setup(g))
        self.assertAlmostEqual(gann_bp8.setup(g)["b1"], 89.5)
        self.assertTrue(gann_bp8.describe(g).startswith("NEW"))

    def test_drops_off_once_the_measured_move_is_reached(self):
        g = self.build(92, 2_000_000)
        closes = list(g["structure"].closes) + [105.0, 109.0, 110.0]   # top 100.5 + (100.5 - 91.5) = 109.5
        vols = list(g["structure"].volumes) + [1_000_000] * 3
        g = item(bars_from_closes(closes, vols))
        self.assertIn("measured-move target not reached yet", gann_bp8.SCREEN.failed_rules(g))

    def test_drops_off_after_close_below_second_bottom(self):
        g = self.build(92, 2_000_000)
        closes = list(g["structure"].closes) + [98.0, 94.0, 91.0]
        vols = list(g["structure"].volumes) + [1_000_000] * 3
        g = item(bars_from_closes(closes, vols))
        self.assertIn("no close back below the top since", gann_bp8.SCREEN.failed_rules(g))

    def test_drops_off_after_close_back_below_the_top(self):
        g = self.build(92, 2_000_000)
        self.assertEqual(gann_bp8.trade(g)["stop"], gann_bp8.setup(g)["top_price"])
        closes = list(g["structure"].closes) + [100.0]   # top is 100.5
        vols = list(g["structure"].volumes) + [1_000_000]
        g = item(bars_from_closes(closes, vols))
        self.assertIn("no close back below the top since", gann_bp8.SCREEN.failed_rules(g))


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

    def test_fires_on_the_day_the_decline_beats_biggest_reaction(self):
        closes, top = self.advance()
        decline = ramp(top, top * 0.97, 3)
        # The first day it passes is the break day: NEW then, ONGOING the day after.
        n = next(k for k in range(1, 4)
                 if not gann_selling_points.SCREEN.failed_rules(item(bars_from_closes(closes + decline[:k]), regime="downtrend")))
        g = item(bars_from_closes(closes + decline[:n]), regime="downtrend")
        self.assertIn("#4 size", gann_selling_points.describe(g))
        self.assertTrue(gann_selling_points.describe(g).startswith("NEW"))
        g = item(bars_from_closes(closes + decline[:n] + [decline[n - 1] - 0.1]), regime="downtrend")
        self.assertTrue(gann_selling_points.describe(g).startswith("ONGOING"))

    def test_old_trend_break_stays_listed_as_ongoing(self):
        closes, top = self.advance()
        g = item(bars_from_closes(closes + ramp(top, top * 0.85, 10)))
        self.assertEqual(gann_selling_points.SCREEN.failed_rules(g), [])
        self.assertTrue(gann_selling_points.describe(g).startswith("ONGOING since"))

    def test_small_short_dip_does_not_fire(self):
        closes, top = self.advance()
        g = item(bars_from_closes(closes + [top - 0.3, top - 0.1]))
        self.assertEqual(gann_selling_points.SCREEN.failed_rules(g),
                         ["decline bigger or longer than any reaction in the advance"])


class RsiBearDivergenceTests(unittest.TestCase):
    # Peaks: 200 (RSI 95, outside the zone), 210 (RSI 88, high 130), 225 (RSI 84, high 135).
    # Price pivot low at 218 (110) is the protective stop.
    RSI = {200: 95.0, 210: 88.0, 225: 84.0}
    HIGHS = {200: 140.0, 210: 130.0, 225: 135.0}

    def build(self, rsi=None, highs=None):
        s = shaped(227, highs={**self.HIGHS, **(highs or {})}, lows={218: 110.0}, rsi={**self.RSI, **(rsi or {})})
        return {**item(s), "tier": "core_owned", "owned": True}

    def test_fires_with_the_protective_stop(self):
        g = self.build()
        self.assertEqual(rsi_bear_resistance_divergence.SCREEN.failed_rules(g), [], rsi_bear_resistance_divergence.setup(g))
        x = rsi_bear_resistance_divergence.setup(g)
        self.assertEqual((x["t1"], x["t2"]), (210, 225))
        self.assertIn("Protective sell stop under 110.00", rsi_bear_resistance_divergence.describe(g))
        self.assertIn("lower high in RSI", rsi_bear_resistance_divergence.describe(g))

    def test_only_the_previous_in_zone_peak_counts(self):
        # RSI 89 at high 121, then 81 at 125, then 84 at 130: 84 is not lower than 81, so no alert,
        # even though it would be lower than the older 89.
        g = self.build(rsi={200: 89.0, 210: 81.0, 225: 84.0}, highs={200: 121.0, 210: 125.0, 225: 130.0})
        self.assertIsNone(rsi_bear_resistance_divergence.setup(g)["t1"])
        self.assertIn("lower RSI high, higher price high than the previous 80-90 peak",
                      rsi_bear_resistance_divergence.SCREEN.failed_rules(g))

    def test_new_peak_must_be_inside_80_90(self):
        g = self.build(rsi={225: 78.0})
        self.assertIn("new RSI peak inside Bull Resistance 80-90", rsi_bear_resistance_divergence.SCREEN.failed_rules(g))

    def test_no_alert_without_a_higher_price_high(self):
        g = self.build(highs={225: 125.0})
        self.assertEqual(rsi_bear_resistance_divergence.SCREEN.failed_rules(g),
                         ["lower RSI high, higher price high than the previous 80-90 peak"])


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

    def test_reads_newest_balances_and_hides_account_ids(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            def write(name, accounts):
                with open(os.path.join(d, name), "w") as f:
                    json.dump({"accounts": accounts}, f)
            write("ibkr_balances_20260101_000000.json", [{"account_id": "U0000001", "net_liquidation": 1.0}])
            write("ibkr_balances_20260201_000000.json", [
                {"account_id": "U1234567", "as_of": "20260130", "currency": "CAD", "net_liquidation": 50000.0, "cash": 1000.0},
                {"account_id": "U7654321", "as_of": "20260130", "currency": "CAD", "net_liquidation": 25000.0, "cash": None},
            ])
            old_env = os.environ.get("PREMARKET_WATCHLIST_DIR")
            os.environ["PREMARKET_WATCHLIST_DIR"] = d
            try:
                b = watchlist_universe.load_balances()
                self.assertEqual(b["source_file"], "ibkr_balances_20260201_000000.json")
                self.assertEqual([a["account"] for a in b["accounts"]], ["…567", "…321"])
                self.assertNotIn("U1234567", json.dumps(b))
                self.assertEqual(b["total_net_liquidation"], 75000.0)
                self.assertEqual(b["risk_per_trade"], {"…567": 1000.0, "…321": 500.0})
                os.environ["PREMARKET_WATCHLIST_DIR"] = os.path.join(d, "missing")
                self.assertIsNone(watchlist_universe.load_balances())
            finally:
                if old_env is None:
                    os.environ.pop("PREMARKET_WATCHLIST_DIR", None)
                else:
                    os.environ["PREMARKET_WATCHLIST_DIR"] = old_env


class ScanWiringTests(unittest.TestCase):
    def test_setups_blocked_only_by_spy_wait_on_the_market(self):
        import scan
        s = shaped(212, lows={200: 90.0, 210: 95.0})
        row = {"ticker": "T", "tier": "core_candidate", "source_lists": ["Blue"], "owned": False}
        for regime, hits, waiting in (("choppy", [], ["T"]), ("uptrend", ["T"], [])):
            block = scan.build_watchlist_screens([row], {"T": s}, regime)["lost_forecasting"]
            self.assertEqual((block["hits"], block["waiting_on_market"]), (hits, waiting))
            self.assertEqual(block["waiting_count"], len(waiting))
            self.assertNotIn("T", [n["ticker"] for n in block["near_misses"]])
        note = scan.build_watchlist_screens([row], {"T": s}, "choppy")["lost_forecasting"]["waiting_details"]["T"]["note"]
        self.assertTrue(note.startswith("NEW"), note)

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
        self.assertEqual(set(blocks), {"lost_forecasting", "rsi_bull_support_divergence", "rsi_bull_bear_support_divergence",
                                       "gann_bp7", "gann_bp8",
                                       "gann_selling_points", "rsi_bear_resistance_divergence"})
        for block in blocks.values():
            self.assertEqual(block["scanned"], 1 if block["kind"] == "alert" else 151)
            self.assertLessEqual(len(block["hits"]), 8)
            self.assertEqual(set(block["hits"]), set(block["hit_details"]))
            for miss in block["near_misses"]:
                self.assertEqual("note" in miss, block["kind"] == "alert")
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


if __name__ == "__main__":
    unittest.main()
