"""
daily_structure.py - shared chart math for the watchlist screens.

Plain Python over finished daily bars, no network and no AI. Every watchlist
screen reads the same Structure, so pivots, RSI and swing levels are computed
once per ticker and mean the same thing in every screen.

Definitions follow the source material the Lab screens come from:
- A pivot low (high) is a bar whose low (high) is lower (higher) than the bars
  on both sides of it, the 3-bar pivot used in Hima Reddy's Lost Forecasting.
- An RSI trough (peak) is the same idea applied to RSI(14) values.
- RSI is Wilder's RSI(14).
"""

from dataclasses import dataclass, field

RSI_PERIOD = 14
CHOP_PERIOD = 14
CHOP_TRENDING_MAX = 61.8   # Choppiness Index above this reads as a sideways, choppy tape


def wilder_rsi(closes, period=RSI_PERIOD):
    """RSI per bar, None until there is enough history."""
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def pivot_lows(values):
    """Indexes of 3-bar pivot lows. The newest bar can't be one yet, it has no right side."""
    return [
        i for i in range(1, len(values) - 1)
        if None not in (values[i - 1], values[i], values[i + 1])
        and values[i] < values[i - 1] and values[i] < values[i + 1]
    ]


def pivot_highs(values):
    return [
        i for i in range(1, len(values) - 1)
        if None not in (values[i - 1], values[i], values[i + 1])
        and values[i] > values[i - 1] and values[i] > values[i + 1]
    ]


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def choppiness(highs, lows, closes, n=CHOP_PERIOD):
    """Choppiness Index: near 100 is sideways, near 0 is a clean trend."""
    import math
    if len(closes) < n + 1:
        return None
    true_ranges = []
    for i in range(len(closes) - n, len(closes)):
        prev_close = closes[i - 1]
        true_ranges.append(max(highs[i], prev_close) - min(lows[i], prev_close))
    span = max(highs[-n:]) - min(lows[-n:])
    if span <= 0:
        return None
    return 100.0 * math.log10(sum(true_ranges) / span) / math.log10(n)


@dataclass
class Structure:
    dates: list
    opens: list
    highs: list
    lows: list
    closes: list
    volumes: list
    rsi: list = field(default_factory=list)
    price_pivot_lows: list = field(default_factory=list)
    price_pivot_highs: list = field(default_factory=list)
    rsi_troughs: list = field(default_factory=list)
    rsi_peaks: list = field(default_factory=list)
    sma_50: float = None
    sma_200: float = None
    rvol: float = None          # last finished day's volume over the prior 20-day average
    vwap_20: float = None       # 20-day volume-weighted average price
    chop: float = None

    @property
    def last(self):
        return len(self.closes) - 1

    @property
    def close(self):
        return self.closes[-1]

    def date(self, i):
        return str(self.dates[i])[:10]

    def bars_ago(self, i):
        return self.last - i

    def highest_high(self, start, end):
        """Index of the highest high in [start, end]."""
        return max(range(start, end + 1), key=lambda i: self.highs[i])

    def lowest_low(self, start, end):
        return min(range(start, end + 1), key=lambda i: self.lows[i])

    def summary(self):
        """Small, JSON-friendly snapshot for the packet."""
        def r(x, d=2):
            return round(x, d) if x is not None else None
        return {
            "as_of": self.date(self.last),
            "close": r(self.close),
            "rsi_14": r(self.rsi[-1], 1) if self.rsi else None,
            "sma_50": r(self.sma_50),
            "sma_200": r(self.sma_200),
            "rvol": r(self.rvol),
            "vwap_20": r(self.vwap_20),
        }


def reactions(s, start, end):
    """Pullbacks inside an advance from bar start to bar end, as Gann measures them.

    Each reaction runs from a high to the lowest low before price makes a new
    high. Returns dicts with peak/trough indexes, size in % and time in bars.
    """
    out = []
    peak = start
    trough = None
    for i in range(start + 1, end + 1):
        if s.highs[i] > s.highs[peak]:
            if trough is not None:
                out.append(_reaction(s, peak, trough))
            peak, trough = i, None
        elif trough is None or s.lows[i] < s.lows[trough]:
            trough = i
    return out


def _reaction(s, peak, trough):
    return {
        "peak": peak,
        "trough": trough,
        "size_pct": 100.0 * (s.highs[peak] - s.lows[trough]) / s.highs[peak],
        "bars": trough - peak,
    }


def build(dates, opens, highs, lows, closes, volumes):
    """Structure from finished daily bars, oldest first. Today's partial bar must already be dropped."""
    s = Structure(
        dates=list(dates), opens=list(opens), highs=list(highs),
        lows=list(lows), closes=list(closes), volumes=list(volumes),
    )
    s.rsi = wilder_rsi(s.closes)
    s.price_pivot_lows = pivot_lows(s.lows)
    s.price_pivot_highs = pivot_highs(s.highs)
    s.rsi_troughs = pivot_lows(s.rsi)
    s.rsi_peaks = pivot_highs(s.rsi)
    s.sma_50 = sma(s.closes, 50)
    s.sma_200 = sma(s.closes, 200)
    if len(s.volumes) >= 21:
        avg = sum(s.volumes[-21:-1]) / 20
        s.rvol = s.volumes[-1] / avg if avg else None
    if len(s.closes) >= 20:
        typical = [(h + l + c) / 3 for h, l, c in zip(s.highs[-20:], s.lows[-20:], s.closes[-20:])]
        vol = sum(s.volumes[-20:])
        s.vwap_20 = sum(t * v for t, v in zip(typical, s.volumes[-20:])) / vol if vol else None
    s.chop = choppiness(s.highs, s.lows, s.closes)
    return s


def regime(s):
    """Trend state for an index ETF: uptrend, downtrend or choppy."""
    if s is None or s.sma_50 is None or s.sma_200 is None:
        return {"state": "unknown"}
    trending = s.chop is not None and s.chop < CHOP_TRENDING_MAX
    if trending and s.close > s.sma_50 > s.sma_200:
        state = "uptrend"
    elif trending and s.close < s.sma_50 < s.sma_200:
        state = "downtrend"
    else:
        state = "choppy"
    return {
        "state": state,
        "close": round(s.close, 2),
        "sma_50": round(s.sma_50, 2),
        "sma_200": round(s.sma_200, 2),
        "choppiness_14": round(s.chop, 1) if s.chop is not None else None,
        "as_of": s.date(s.last),
    }


def from_dataframe(df):
    """Structure from a yfinance daily DataFrame (Open/High/Low/Close/Volume columns)."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return build(
        [d.date() for d in df.index],
        df["Open"].astype(float).tolist(),
        df["High"].astype(float).tolist(),
        df["Low"].astype(float).tolist(),
        df["Close"].astype(float).tolist(),
        df["Volume"].fillna(0).astype(float).tolist(),
    )
