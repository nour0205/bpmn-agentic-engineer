from __future__ import annotations

from .models import Recommendation

_LEVEL = {"high": 0, "medium": 1, "low": 2}


def rank_recommendations(items: list[Recommendation]) -> list[Recommendation]:
    return sorted(
        items,
        key=lambda item: (
            _LEVEL[item.confidence],
            0 if item.executable_by_current_engine else 1,
            _LEVEL[item.impact],
            -len(item.evidence),
            -len(item.affected_elements),
            item.category,
            item.id,
        ),
    )
