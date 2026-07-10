# Watchlist Criteria

This is the source of truth for the scanner. These are the two validated setups, backtested, not vibes. If the scanner and this file ever disagree, this file wins and the scanner needs a fix.

---

## Day Trading Watchlist: "Trend Join Long"

Backtest: 54.6% win rate, profit factor 1.59, 280 trades.

### Premarket selection (all required)

- Gap % vs prev close > 3%
- Price > $3
- Market cap > $1B
- Premarket RVOL > 1.5
- Price breaking above yesterday's high

If a name is missing even one of these, it doesn't make the day trading list. No exceptions, no "but it feels strong."

### Intraday plan

- **Window**: 10:00am to 3:30pm ET. Nothing before 10, nothing new after 3:30.
- **Trigger**: price > premarket high AND > prior high-of-day
- **Stop (1R)**: 1% below premarket high, or the LOD, whichever is lower
- **Scale out**: 1/3 off at +1R, 1/3 off at +2R
- **Runner**: trail the last 1/3 on the 21-EMA
- **Flat by 3:51pm**, no holds into the close

---

## Swing Watchlist

Backtest: 57.6% win rate, PF 5.34 on news catalysts. 44.7% win rate, PF 2.57 on earnings catalysts. Two different animals, both count as swing.

### Premarket selection (all required)

- Gap % >= 8%
- Price > $3
- Open > yesterday's high
- Open > 200-day SMA
- Market cap >= $800M
- A real catalyst: earnings on the gap day, or news if there's no earnings

Same deal as day trading, all boxes checked or it doesn't get listed.

### Entry and exit management

Not built yet. Swing names on the report are starter ideas only. Do not attach stops or targets to them and do not let the analyst pass invent any. If it's not backtested, it doesn't go on the page.

---

## Notes for the scanner

- Day trading and swing lists are built from separate, independent criteria. A ticker can qualify for both, neither, or one but not the other.
- Every field above is a hard filter, not a scoring weight. This is pass/fail, not a ranking model.
- Catalyst on the swing side has to be real and checkable (an actual earnings report or actual news), not just "stock is up."
