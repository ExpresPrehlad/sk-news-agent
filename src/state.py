"""
Stav medzi behmi.

GitHub Actions runner je efemérny, preto sa stav drží v JSON súbore, ktorý
workflow po behu commitne späť do repa. Formát je zámerne primitívny:

{
  "seen": { "<uid>": <first_seen_unix_ts>, ... },
  "meta": { "last_run_ts": ..., "last_digest_ts": ... }
}

Pravidlá:
- `seen` sa pri každom uložení prereže na SEEN_WINDOW_HOURS, aby súbor nerástol.
- Poškodený alebo chýbajúci súbor = čistý štart (prvý beh po ňom môže poslať
  viac článkov naraz — na to je poistka MAX_RAW_ITEMS_PER_RUN v notify vrstve).
"""

from __future__ import annotations

import json
import logging
import os
import time

from .config import SEEN_WINDOW_HOURS

log = logging.getLogger(__name__)


class State:
    def __init__(self, path: str):
        self.path = path
        self.seen: dict[str, float] = {}
        self.meta: dict[str, float] = {}
        self._load()

    # -- I/O ---------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self.path):
            log.info("Stavový súbor %s neexistuje — čistý štart.", self.path)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.seen = {str(k): float(v) for k, v in data.get("seen", {}).items()}
            self.meta = {str(k): float(v) for k, v in data.get("meta", {}).items()}
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
            log.error("Stav %s je poškodený (%s) — čistý štart.", self.path, exc)
            self.seen, self.meta = {}, {}

    def save(self) -> None:
        self._prune()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seen": self.seen, "meta": self.meta}, f, ensure_ascii=False)
        os.replace(tmp, self.path)  # atomický zápis — polovičný súbor nikdy

    # -- Deduplikácia ------------------------------------------------------

    def is_new(self, uid: str) -> bool:
        return uid not in self.seen

    def mark_seen(self, uid: str) -> None:
        self.seen[uid] = time.time()

    def _prune(self) -> None:
        cutoff = time.time() - SEEN_WINDOW_HOURS * 3600
        before = len(self.seen)
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        removed = before - len(self.seen)
        if removed:
            log.info("Stav: odstránených %d starých záznamov.", removed)

    # -- Meta --------------------------------------------------------------

    def get_meta(self, key: str, default: float = 0.0) -> float:
        return self.meta.get(key, default)

    def set_meta(self, key: str, value: float) -> None:
        self.meta[key] = value
