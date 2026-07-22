"""
GitHub Actions Step Summary — krátky, čitateľný prehľad behu, viditeľný
priamo na stránke behu v Actions UI (nie je potrebné rozbaľovať surové
logy). Mimo GitHub Actions (lokálny beh) je GITHUB_STEP_SUMMARY
nenastavené — funkcia sa potom ticho nič nerobí.
"""

from __future__ import annotations

import os


def write(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    except OSError:
        pass  # diagnostika nesmie zhodiť beh
