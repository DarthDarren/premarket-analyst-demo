"""
screens/base.py - the shape every screen plug-in follows.

A screen is a set of pass/fail rules run against a universe of tickers. Every
rule is a hard filter, not a scoring weight, same as WATCHLIST_CRITERIA.md.

Two universes exist:
- GAPPERS: each enriched premarket gapper (the original Day and Swing screens).
- WATCHLIST: each ticker in the newest Screener watchlist CSV, with a
  daily_structure.Structure under item["structure"] and the SPY trend state
  under item["market_regime"].
"""

from dataclasses import dataclass, field
from typing import Callable

VALIDATED = "validated"
EXPERIMENTAL = "experimental"

GAPPERS = "gappers"
WATCHLIST = "watchlist"

SETUP = "setup"   # a buy idea
ALERT = "alert"   # a warning on a stock Darren already owns, shown in Portfolio Alerts


@dataclass
class Rule:
    label: str
    check: Callable[[dict], bool]


@dataclass
class Screen:
    id: str
    name: str
    status: str                 # VALIDATED gets a full watchlist section, EXPERIMENTAL goes in the Lab
    criteria: str               # plain-English rule description the prompts quote to the reader
    params: dict                # thresholds, written to packet.scan_params so the numbers are visible
    rules: list                 # list of Rule, every one must pass
    order: int = 100            # position in the report, lower comes first
    plan: str = ""              # entry/exit plan, only for validated screens with a backtested plan
    flag: str = ""              # per-gapper boolean field name, defaults to "<id>_eligible"
    rules_key: str = ""         # key under packet.scan_params, defaults to "<id>_rules"
    builtin: bool = False       # True for the original Day and Swing screens the prompts name directly
    backtest: dict = field(default_factory=dict)
    universe: str = GAPPERS     # GAPPERS or WATCHLIST
    tiers: tuple = ()           # WATCHLIST only: Screener tiers to scan, empty means every tier
    describe: Callable = None   # WATCHLIST only: item -> one-line note on why it hit, for the analysts
    max_hits: int = 8           # WATCHLIST only: cap on hits sent to the analysts, keeps AI usage small
    kind: str = SETUP           # SETUP (buy idea) or ALERT (warning on an owned stock)

    def __post_init__(self):
        if self.status not in (VALIDATED, EXPERIMENTAL):
            raise ValueError(f"screen {self.id}: status must be '{VALIDATED}' or '{EXPERIMENTAL}'")
        if self.universe not in (GAPPERS, WATCHLIST):
            raise ValueError(f"screen {self.id}: universe must be '{GAPPERS}' or '{WATCHLIST}'")
        if self.kind not in (SETUP, ALERT):
            raise ValueError(f"screen {self.id}: kind must be '{SETUP}' or '{ALERT}'")
        self.flag = self.flag or f"{self.id}_eligible"
        self.rules_key = self.rules_key or f"{self.id}_rules"

    def failed_rules(self, gapper):
        failed = []
        for rule in self.rules:
            try:
                ok = bool(rule.check(gapper))
            except Exception:
                ok = False
            if not ok:
                failed.append(rule.label)
        return failed

    def passes(self, gapper):
        return not self.failed_rules(gapper)


def daily(gapper, key):
    # Most rules read either a top-level gapper field or one from daily_metrics.
    return (gapper.get("daily_metrics") or {}).get(key)


def market_ok(item, allowed=("uptrend",)):
    # Watchlist buy screens only fire when the broad market (SPY) is trending the right way.
    return item.get("market_regime") in allowed


def memo(item, key, fn):
    # Watchlist rules share one setup search per ticker instead of redoing it in every rule.
    cache = item.setdefault("_memo", {})
    if key not in cache:
        cache[key] = fn(item["structure"])
    return cache[key]
