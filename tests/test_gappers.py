import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import scan  # noqa: E402
from screens import day_trading, swing  # noqa: E402

ET = scan.ET


def gapper(**kw):
    g = {"ticker": "TEST", "gap_pct": 9.0, "price": 22.0, "market_cap": 2e9, "rvol": 2.0, "rvol_source": "premarket",
         "catalyst_found": True,
         "daily_metrics": {"prior_day_high": 21.0, "prior_close": 20.0, "sma_200": 15.0, "today_open": 22.0}}
    g.update(kw)
    return g


class QuoteTests(unittest.TestCase):
    QUOTE = {"symbol": "FIGS", "regularMarketPrice": 17.74, "regularMarketPreviousClose": 15.78,
             "regularMarketChangePercent": 12.42, "preMarketPrice": 18.5, "preMarketChangePercent": 4.28,
             "regularMarketVolume": 9_000_000}

    def test_premarket_uses_the_premarket_print_against_yesterdays_close(self):
        q = scan.normalize_quote(self.QUOTE, premarket=True)
        self.assertEqual((q["price"], q["prev_close"], q["gap_pct"]), (18.5, 17.74, 4.28))

    def test_no_premarket_print_means_no_gap(self):
        q = dict(self.QUOTE)
        q.pop("preMarketPrice")
        q = scan.normalize_quote(q, premarket=True)
        self.assertIsNone(q["gap_pct"])

    def test_regular_session_unchanged(self):
        q = scan.normalize_quote(self.QUOTE, premarket=False)
        self.assertEqual((q["price"], q["gap_pct"]), (17.74, 12.42))

    def test_gap_downs_do_not_take_a_slot(self):
        movers = [{"ticker": "UP", "gap_pct": 5.0, "price": 10}, {"ticker": "DOWN", "gap_pct": -20.0, "price": 10}]
        self.assertEqual([m["ticker"] for m in scan.filter_gappers(movers)], ["UP"])


class CatalystTests(unittest.TestCase):
    NOW = datetime(2026, 10, 13, 8, 30, tzinfo=ET)

    def test_fair_value_is_not_fair_isaac(self):
        tokens = scan.build_name_tokens("Fair Isaac Corporation")
        self.assertFalse(scan.headline_matches_ticker("Dar Global Stock Stays Near Fair Value On Earnings Today", "FICO", tokens))
        self.assertTrue(scan.headline_matches_ticker("Fair Isaac raises guidance", "FICO", tokens))
        self.assertTrue(scan.headline_matches_ticker("FICO jumps after earnings", "FICO", tokens))

    def test_earnings_on_the_gap(self):
        self.assertEqual(scan.classify_catalyst([], "2026-10-12", "2026-10-12", self.NOW), "earnings")
        self.assertEqual(scan.classify_catalyst([], "2026-11-12", "2026-10-12", self.NOW), None)

    def test_only_recent_headlines_count(self):
        old = {"published": "2026-10-09T14:00:00Z"}
        fresh = {"published": "Mon, 12 Oct 2026 21:15:00 GMT"}
        undated = {"published": ""}
        self.assertIsNone(scan.classify_catalyst([old, undated], None, "2026-10-12", self.NOW))
        self.assertEqual(scan.classify_catalyst([old, fresh], None, "2026-10-12", self.NOW), "news")


class IntradayTests(unittest.TestCase):
    def test_premarket_rvol_compares_the_same_stretch_of_premarket(self):
        idx, vols, closes = [], [], []
        for day, pm_vol in ((8, 1000), (9, 3000), (12, 4000)):
            for minute in range(0, 120, 5):  # 7:00 to 8:55
                idx.append(pd.Timestamp(2026, 10, day, 7, 0, tz=ET) + pd.Timedelta(minutes=minute))
                vols.append(pm_vol / 24)
                closes.append(10.0 + day)
        hist = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": vols},
                            index=pd.DatetimeIndex(idx))
        now = datetime(2026, 10, 12, 9, 0, tzinfo=ET)
        out = scan.intraday_levels_from_bars(hist, now)
        self.assertAlmostEqual(out["premarket_rvol"], 4000 / 2000)
        self.assertEqual(out["last_price"], 22.0)

    def test_no_bars_today(self):
        idx = pd.DatetimeIndex([pd.Timestamp(2026, 10, 9, 8, 0, tz=ET)])
        hist = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [5.0]}, index=idx)
        out = scan.intraday_levels_from_bars(hist, datetime(2026, 10, 12, 8, 30, tzinfo=ET))
        self.assertIsNone(out["last_price"])


class ScreenTests(unittest.TestCase):
    def test_day_passes_on_a_real_gap(self):
        self.assertEqual(day_trading.SCREEN.failed_rules(gapper()), [])

    def test_day_needs_real_premarket_rvol(self):
        self.assertEqual(day_trading.SCREEN.failed_rules(gapper(rvol_source="prior_session_stand_in")), ["premarket RVOL > 1.5"])

    def test_swing_passes_and_needs_a_200_day_sma(self):
        self.assertEqual(swing.SCREEN.failed_rules(gapper()), [])
        g = gapper()
        g["daily_metrics"]["sma_200"] = None
        self.assertEqual(swing.SCREEN.failed_rules(g), ["open > 200-day SMA"])

    def test_swing_needs_a_catalyst(self):
        self.assertEqual(swing.SCREEN.failed_rules(gapper(catalyst_found=False)), ["real catalyst"])


if __name__ == "__main__":
    unittest.main()
