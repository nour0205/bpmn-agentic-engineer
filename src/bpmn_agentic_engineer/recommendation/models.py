from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CATEGORIES = {
    "AUTOMATION",
    "REDUNDANCY_REMOVAL",
    "CONTROL_INSERTION",
    "ACTIVITY_SIMPLIFICATION",
    "LABEL_CLARIFICATION",
    "HANDOFF_REDUCTION",
    "MANUAL_DATA_ENTRY_REDUCTION",
    "SEQUENTIAL_MANUAL_PROCESSING",
    "POTENTIAL_PARALLELIZATION",
}
LEVELS = {"high", "medium", "low"}
OPERATIONS = {
    "insert_task_before",
    "insert_task_after",
    "rename_element",
    "remove_element",
    "replace_linear_task_sequence",
    "analysis_only",
}


@dataclass(frozen=True)
class RecommendationEvidence:
    finding_code: str
    element_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ExistingElement:
    element_id: str
    name: str | None
    type: str
    process_id: str
    lane: str | None


@dataclass(frozen=True)
class ProposedChange:
    kind: str
    name: str | None = None
    type: str | None = None
    lane: str | None = None
    anchor_element_id: str | None = None
    position: str | None = None


@dataclass(frozen=True)
class Recommendation:
    id: str
    category: str
    title: str
    problem: str
    evidence: tuple[RecommendationEvidence, ...]
    recommendation: str
    affected_elements: tuple[ExistingElement, ...]
    proposed_changes: tuple[ProposedChange, ...]
    suggested_operation: str
    executable_by_current_engine: bool
    confidence: str
    impact: str
    complexity: str
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationResult:
    source_file: str
    process_name: str | None
    goal: str | None
    recommendations: tuple[Recommendation, ...]
    rejected_recommendations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "process_name": self.process_name,
            "goal": self.goal,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "recommendation_count": len(self.recommendations),
            "rejected_recommendations": self.rejected_recommendations,
        }
