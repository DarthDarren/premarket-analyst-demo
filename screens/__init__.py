"""
screens - one file per screen. Drop a new module in this folder that defines
SCREEN = Screen(...) and scan.py picks it up on the next run. Files starting
with an underscore are skipped, so _template.py is never loaded.
"""

import importlib
import pkgutil

from .base import EXPERIMENTAL, GAPPERS, VALIDATED, WATCHLIST, Rule, Screen, daily, market_ok, memo  # noqa: F401


def load_screens():
    screens = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        screen = getattr(module, "SCREEN", None)
        if not isinstance(screen, Screen):
            raise TypeError(f"screens/{info.name}.py must define SCREEN = Screen(...)")
        screens.append(screen)

    ids = [s.id for s in screens]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate screen ids: {sorted(dupes)}")
    return sorted(screens, key=lambda s: (s.order, s.id))
