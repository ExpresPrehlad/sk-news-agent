"""
Rozvrh behu — logika nad SCHEDULE_BANDS (tabuľka pásiem definovaná v
config.py). Každé pásmo má vlastný interval zberu aj syntézy; mimo všetkých
pásiem systém spí.

Rieši sa v Pythone, nie v cron výraze workflow súboru: GitHub Actions cron
beží vždy v UTC a nerozlišuje SEČ/SELČ (letný/zimný čas). `zoneinfo`
(štandardná knižnica) prepočet rieši automaticky a natrvalo, bez ručných
zásahov dvakrát ročne.

Manuálne spustenie (workflow_dispatch, alebo lokálne `python main.py`)
rozvrh nerešpektuje — vždy reálne zbiera. Iba automatický cron beh
(`schedule` event, rozpoznaný cez GITHUB_EVENT_NAME) sa riadi pásmami.
"""

from __future__ import annotations

import os
import time as _time_mod
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import (
    ACTIVE_HOURS_TZ,
    DEFAULT_SYNTHESIS_INTERVAL_MINUTES,
    SCHEDULE_BANDS,
    ScheduleBand,
)

# Rozvrh sa rešpektuje pri:
# 1. natívnom GitHub cron behu (schedule event),
# 2. externom záložnom cron triggeri (cron-job.org a pod.), ktorý volá
#    workflow_dispatch s inputs.backup_trigger=true — je to náhrada za
#    natívny cron pri jeho výpadkoch (best-effort, viď diskusia v chate
#    z 22.7.2026), NIE samostatný nezávislý kanál bežiaci mimo rozvrhu.
# Obyčajné ručné "Run workflow" kliknutie (backup_trigger=false, default)
# rozvrh naďalej obchádza — nech ide kedykoľvek testovať bez čakania.
IS_SCHEDULED_RUN = (
    os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    or os.environ.get("BACKUP_TRIGGER", "").lower() == "true"
)


def current_band(now: datetime | None = None) -> ScheduleBand | None:
    """
    Aktívne pásmo pre daný čas (default: teraz, Bratislava), alebo None,
    ak je mimo všetkých pásiem (systém spí).
    """
    if now is None:
        now = datetime.now(ZoneInfo(ACTIVE_HOURS_TZ))
    weekday, t = now.weekday(), now.time()
    for band in SCHEDULE_BANDS:
        if weekday in band.weekdays and band.start <= t < band.end:
            return band
    return None


def should_collect(state) -> tuple[bool, ScheduleBand | None]:
    """
    Rozhodne, či má tento beh reálne zbierať. Vráti (má_zbierať, pásmo).

    Manuálny beh vždy zbiera (pásmo môže byť None, ak je mimo okna — vtedy
    sa použije DEFAULT_SYNTHESIS_INTERVAL_MINUTES pre prípadnú syntézu).
    Automatický (cron) beh zbiera len ak je v pásme A uplynul jeho
    collect_minutes interval od posledného zberu.
    """
    band = current_band()
    if not IS_SCHEDULED_RUN:
        return True, band
    if band is None:
        return False, None
    last = state.get_meta("last_collection_ts")
    due = _time_mod.time() - last >= band.collect_minutes * 60
    return due, band


def synthesis_interval_minutes(band: ScheduleBand | None) -> int:
    """Interval syntézy pre dané pásmo, alebo fallback mimo pásiem."""
    return band.synthesis_minutes if band else DEFAULT_SYNTHESIS_INTERVAL_MINUTES
