"""
screens/base.py - the shape every screen plug-in follows.

A screen is a set of pass/fail rules run against each enriched gapper. Every
rule is a hard filter, not a scoring weight, same as WATCHLIST_CRITERIA.md.
"""

from dataclasses import dataclass, field
from typing import Callable

VALIDATED = "validated"
EXPERIMENTAL = "experimental"


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

    def __post_init__(self):
        if self.status not in (VALIDATED, EXPERIMENTAL):
            raise ValueError(f"screen {self.id}: status must be '{VALIDATED}' or '{EXPERIMENTAL}'")
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
