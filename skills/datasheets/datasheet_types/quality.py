"""The extraction quality score the datasheet readers use.

``current_quality`` re-scores a cached v1.4 extraction with the rubric in
``scripts/datasheet_score.py`` and keeps the lower of the stored and current
score, so a cache scored under an older, more generous rubric is not trusted
on its old score.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from .trust_gating import finite_score

_SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")


def _rubric_score(raw: dict) -> int:
    if _SCRIPTS not in sys.path:
        sys.path.append(_SCRIPTS)
    from datasheet_score import score_v14_extraction
    return score_v14_extraction(raw)["score"]


def current_quality(raw: dict) -> Optional[float]:
    """The stored ``extraction.quality_score``, lowered to the current rubric's
    score for a v1.4-shaped extraction (one with a ``base`` block).

    None when the stored score is missing or not a finite number. The lower of
    the two is kept so a score set low by hand stays low; a v1.3-shaped dict
    keeps its stored score.
    """
    block = raw.get("extraction")
    stored = finite_score(block.get("quality_score")) if isinstance(block, dict) else None
    if stored is None or not isinstance(raw.get("base"), dict):
        return stored
    return min(stored, _rubric_score(raw))
