"""
Stav medzi behmi.

GitHub Actions runner je efemérny, preto sa stav drží v JSON súbore, ktorý
workflow po behu commitne späť do repa. Formát:

{
  "seen": { "<uid>": <first_seen_unix_ts>, ... },
  "recent": [ {"u": uid, "s": zdroj, "t": titulok, "p": perex, "l": link, "ts": ...}, ... ],
  "meta": { "last_run_ts": ..., "last_synthesis_ts": ... }
}

Pravidlá:
- `seen` sa pri každom uložení prereže na SEEN_WINDOW_HOURS.
- `recent` je rolling buffer článkov pre syntézu, prerezáva sa na
  RECENT_BUFFER_HOURS.
- Poškodený alebo chýbajúci súbor = čistý štart.
"""

from __future__ import annotations

import json
import logging
import os
import time

from .config import RECENT_BUFFER_HOURS, SEEN_WINDOW_HOURS

log = logging.getLogger(__name__)


class State:
    def __init__(self, path: str):
        self.path = path
        self.seen: dict[str, float] = {}
        self.recent: list[dict] = []
        self.meta: dict[str, float] = {}
        self.last_digest: dict = {}       # {"topics": [...], "model": ..., "ts": ...}
        self.digest_topic_history: list[dict] = []  # [{"headline":..., "ts":...}, ...]
        self.recent_alerts: list[dict] = []  # rolling história pre stránku
        self.source_status: dict[str, dict] = {}  # id -> {"ok", "error", "ts"}
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
            self.recent = [r for r in data.get("recent", []) if isinstance(r, dict)]
            self.meta = {str(k): float(v) for k, v in data.get("meta", {}).items()}
            self.last_digest = data.get("last_digest") or {}
            self.digest_topic_history = [
                h for h in data.get("digest_topic_history", []) if isinstance(h, dict)
            ]
            self.recent_alerts = [
                a for a in data.get("recent_alerts", []) if isinstance(a, dict)
            ]
            self.source_status = {
                str(k): v for k, v in data.get("source_status", {}).items()
                if isinstance(v, dict)
            }
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
            log.error("Stav %s je poškodený (%s) — čistý štart.", self.path, exc)
            self.seen, self.recent, self.meta = {}, [], {}
            self.last_digest, self.recent_alerts, self.source_status = {}, [], {}
            self.digest_topic_history = []

    def save(self) -> None:
        self._prune()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            # indent + sort_keys: každý kľúč na vlastnom riadku. Vďaka tomu
            # vie git riadkovo automerge-ovať neprekrývajúce sa zmeny dvoch
            # behov (napr. súbežný cron + manuálny beh) namiesto toho, aby
            # hlásil konflikt na celom jednoriadkovom JSON blobe.
            json.dump(
                {
                    "seen": self.seen,
                    "recent": self.recent,
                    "meta": self.meta,
                    "last_digest": self.last_digest,
                    "digest_topic_history": self.digest_topic_history,
                    "recent_alerts": self.recent_alerts,
                    "source_status": self.source_status,
                },
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        os.replace(tmp, self.path)  # atomický zápis — polovičný súbor nikdy

    # -- Deduplikácia ------------------------------------------------------

    def is_new(self, uid: str) -> bool:
        return uid not in self.seen

    def mark_seen(self, uid: str) -> None:
        self.seen[uid] = time.time()

    # -- Rolling buffer pre syntézu ---------------------------------------

    def add_recent(self, *, uid: str, source: str, title: str,
                   perex: str, link: str) -> None:
        self.recent.append(
            {"u": uid, "s": source, "t": title, "p": perex[:300], "l": link,
             "ts": time.time()}
        )

    def recent_window(self, hours: float) -> list[dict]:
        cutoff = time.time() - hours * 3600
        return [r for r in self.recent if float(r.get("ts", 0)) >= cutoff]

    # -- GitHub Pages: posledný digest, história alertov, zdravie zdrojov --

    def set_last_digest(self, topics: list, model: str) -> None:
        self.last_digest = {
            "topics": [
                {"headline": t.headline, "perex": t.perex, "links": t.links}
                for t in topics
            ],
            "model": model,
            "ts": time.time(),
        }

    def add_digest_history(self, topics: list) -> None:
        """Zaznamená nadpisy zobrazených tém — vstup pre budúcu syntézu, aby
        vedela rozpoznať a nevracať tú istú (nevyvíjajúcu sa) tému opakovane."""
        now = time.time()
        for t in topics:
            self.digest_topic_history.append({"headline": t.headline, "ts": now})

    def recent_digest_headlines(self, hours: float) -> list[str]:
        cutoff = time.time() - hours * 3600
        return [
            h["headline"] for h in self.digest_topic_history
            if float(h.get("ts", 0)) >= cutoff
        ]

    def add_alerts(self, alerts: list, model: str) -> None:
        now = time.time()
        for a in alerts:
            self.recent_alerts.append(
                {"title": a.title, "reason": a.reason, "links": a.links,
                 "model": model, "ts": now}
            )

    def recent_alerts_window(self, hours: float) -> list[dict]:
        cutoff = time.time() - hours * 3600
        return [a for a in self.recent_alerts if float(a.get("ts", 0)) >= cutoff]

    def set_source_status(self, results) -> None:
        for r in results:
            self.source_status[r.source.id] = {
                "name": r.source.name,
                "ok": r.ok,
                "error": r.error,
                "ts": time.time(),
            }

    def _prune(self) -> None:
        cutoff = time.time() - SEEN_WINDOW_HOURS * 3600
        before = len(self.seen)
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        removed = before - len(self.seen)
        if removed:
            log.info("Stav: odstránených %d starých záznamov.", removed)
        rcutoff = time.time() - RECENT_BUFFER_HOURS * 3600
        self.recent = [r for r in self.recent if float(r.get("ts", 0)) >= rcutoff]
        # Alerty držíme viditeľné dlhšie (7 dní) — sú vzácne a hodnotné,
        # na rozdiel od surového bufferu nezaťažujú veľkosť súboru.
        acutoff = time.time() - 7 * 24 * 3600
        self.recent_alerts = [
            a for a in self.recent_alerts if float(a.get("ts", 0)) >= acutoff
        ]
        # História tém pre rotáciu: 4h stačí (viac než dosť pri syntéze
        # každých 15-30 min) — staršie by len zbytočne rástli súbor.
        dcutoff = time.time() - 4 * 3600
        self.digest_topic_history = [
            h for h in self.digest_topic_history if float(h.get("ts", 0)) >= dcutoff
        ]

    # -- Meta --------------------------------------------------------------

    def get_meta(self, key: str, default: float = 0.0) -> float:
        return self.meta.get(key, default)

    def set_meta(self, key: str, value: float) -> None:
        self.meta[key] = value
