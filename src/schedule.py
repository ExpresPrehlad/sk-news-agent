"""
Aktívne hodiny — mimo tohto okna sa AUTOMATICKÝ (cron) beh preskočí úplne,
bez akýchkoľvek volaní (RSS, LLM, Discord, GitHub Pages). Dôvod: cez noc
nikto v redakcii výstup nesleduje, takže nemá zmysel míňať rozpočet ani
počet behov.

Rieši sa tu v Pythone, nie v cron výraze workflow súboru: GitHub Actions
cron beží vždy v UTC a nerozlišuje SEČ/SELČ (letný/zimný čas). Kódovať okno
priamo do cronu by znamenalo ručne prepisovať výraz dvakrát ročne. `zoneinfo`
(štandardná knižnica, žiadna závislosť navyše) prepočet rieši automaticky
a natrvalo.

Manuálne spustenie (workflow_dispatch, alebo lokálne `python main.py`) okno
NEREŠPEKTUJE — vždy prebehne. Iba plánovaný cron beh (`schedule` event) sa
mimo okna preskočí. Rozlíšenie ide cez premennú GITHUB_EVENT_NAME, ktorú
posiela GitHub Actions.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_END, ACTIVE_HOURS_START, ACTIVE_HOURS_TZ

IS_SCHEDULED_RUN = os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def is_active_now() -> bool:
    """True, ak je aktuálny lokálny čas (Bratislava) v aktívnom okne."""
    now = datetime.now(ZoneInfo(ACTIVE_HOURS_TZ)).time()
    return ACTIVE_HOURS_START <= now <= ACTIVE_HOURS_END


def should_run() -> bool:
    """
    Rozhoduje, či má beh pokračovať. Manuálne spustenie prebehne vždy;
    automatický cron beh len v rámci aktívneho okna.
    """
    return (not IS_SCHEDULED_RUN) or is_active_now()
