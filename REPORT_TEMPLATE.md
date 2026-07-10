# Premarket Report Template

This is the fixed skeleton for the daily premarket report. Every section below must appear, in this order, every time. The analyst prompt (Claude and Codex independent passes) and the merge prompt both build off this file, so don't reorder or drop sections. Voice is casual Humbled Trader: talk like a trader who's been burned before and isn't afraid to say so. No em dashes anywhere, use commas or periods instead.

Placeholders are in `{{DOUBLE_BRACES}}`. Instructions for the writer are in *italics* and should be deleted in the final rendered report, not left in.

---

## 1. Title + Dated Subtitle

```
# {{TICKER_OR_MARKET}} Premarket Report
### {{DAY_OF_WEEK}}, {{MONTH}} {{DAY}}, {{YEAR}} — Claude + Codex, Two Independent Passes
```

*Subtitle always names both models and makes clear these are separate passes that get reconciled later, not a single blended take.*

## 2. Disclaimer

*One line, not a paragraph.*

```
Rules pick the watchlist, Claude and Codex judge quality, none of this is financial advice.
```

## 3. Summary

*Three lines max, each doing one job.*

- **The tape in one line**: {{one line on overall market tone, e.g. futures direction, vibe of the morning}}
- **The catch we're watching**: {{the one thing that could flip the whole day, a data print, an event, a name that's acting weird}}
- **Two-brain verdict**: {{one line where Claude and Codex agree or disagree on the day's overall read}}

## 4. Pre-Market Gappers

*List format, one entry per gapper. Each one needs the full catalyst headline, not a summary of it, so readers know exactly what news is moving the stock.*

```
- **{{TICKER}}** {{+/-X%}} premarket — "{{Full catalyst headline as reported}}"
```

Repeat for each gapper worth flagging.

## 5. Day Trading Watchlist

*Table format. Codex check is a short gut check on the setup, not a repeat of the plan. Conviction uses the green/yellow/red key from the bottom of this doc.*

| Ticker | Catalyst | Levels | Plan | Codex Check | Conviction |
|---|---|---|---|---|---|
| {{TICKER}} | {{catalyst}} | {{support/resistance/trigger levels}} | {{entry, target, stop}} | {{Codex's quick take}} | 🟢/🟡/🔴 |

## 6. Swing Watchlist

*Same table logic as day trading, but trend context replaces levels since swings care more about the bigger picture than tick-by-tick triggers.*

| Ticker | Catalyst | Trend Context | Idea | Codex Check | Conviction |
|---|---|---|---|---|---|
| {{TICKER}} | {{catalyst}} | {{where it sits on daily/weekly chart}} | {{swing thesis}} | {{Codex's quick take}} | 🟢/🟡/🔴 |

## 7. Market Trends of the Day

*What's rotating, what sector or theme is leading or lagging, what's the money actually doing today.*

{{2-4 bullets on sector rotation, risk-on/risk-off, thematic moves}}

## 8. Technical Signals for Today

*Index levels, key chart signals, anything technical traders need on their radar.*

{{2-4 bullets on SPX/QQQ/RUT levels, VIX, breadth, notable chart patterns}}

## 9. Economic Data, Rates and the Fed

*Pulled straight from the econ calendar. Include time of release where it matters.*

{{bullets: data releases today, Fed speakers, rate expectations, bond market read}}

## 10. Coming Up

*Forward looking only, nothing about today.*

- **Tomorrow's events**: {{econ data, Fed speakers, macro catalysts}}
- **Tomorrow's earnings**: {{tickers reporting, before/after the bell}}

## 11. Skips and Traps

*Names that looked interesting but didn't make the cut, and why. This is where you save someone from a bad trade.*

{{bullets: ticker, why it's a skip or trap, what would change that}}

## 12. Where the Two Brains Landed

*The reconciliation section. This is the payoff of running two independent passes instead of one.*

- **Where they agreed**: {{the calls both Claude and Codex landed on the same way}}
- **Rules vs discretion**: {{where the rules-based watchlist and the AI judgment pulled in different directions, and who won}}
- **Claude's sharp catch**: {{something Claude flagged that was worth surfacing}}
- **Codex's sharp catch**: {{something Codex flagged that was worth surfacing}}

---

## Conviction Key

- 🟢 Green: high conviction, setup is clean, both brains like it
- 🟡 Yellow: medium conviction, setup works but something's nagging, proceed with a smaller size or tighter stop
- 🔴 Red: low conviction, listed for awareness only, not a real trade idea
