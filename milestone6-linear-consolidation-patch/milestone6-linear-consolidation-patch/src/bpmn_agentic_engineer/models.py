from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BpmnElement:
    id: str
    type: str
    name: str | None = None
    process_id: str | None = None
    lane_id: str | None = None
    lane_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SequenceFlow:
    id: str
    source_ref: str
    target_ref: str
    name: str | None = None
    process_id: str | None = None
    condition_expression: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    element_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["element_ids"] = list(self.element_ids)
        return data


@dataclass(frozen=True)
class ChangeRequest:
    """Normalized representation of a natural-language BPMN change request."""

    request_text: str
    operation: str
    position: str | None = None
    target_query: str | None = None
    target_element_id: str | None = None
    target_process_id: str | None = None
    new_name: str | None = None
    target_lane_name: str | None = None
    source_queries: tuple[str, ...] = field(default_factory=tuple)
    new_bpmn_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_queries"] = list(self.source_queries)
        return data


@dataclass(frozen=True)
class ElementCandidate:
    """A process-aware candidate produced while grounding a request."""

    id: str
    type: str
    name: str | None
    process_id: str | None
    participant_id: str | None
    participant_name: str | None
    lane_id: str | None
    lane_name: str | None
    score: float
    exact_name_match: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannedOperation:
    """One deterministic, atomic operation proposed for later execution."""

    id: str
    operation: str
    parameters: dict[str, Any]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModificationPlan:
    """Read-only proposal. It never mutates the BPMN document."""

    file: str
    request: ChangeRequest
    status: str
    requires_clarification: bool
    requires_approval: bool
    selected_target: dict[str, Any] | None = None
    candidate_matches: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    target_context: dict[str, Any] | None = None
    planned_operations: tuple[PlannedOperation, ...] = field(default_factory=tuple)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    clarification_questions: tuple[str, ...] = field(default_factory=tuple)
    baseline_validation: dict[str, Any] = field(default_factory=dict)
    planner_version: str = "deterministic-v2"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["request"] = self.request.to_dict()
        data["planned_operations"] = [
            operation.to_dict() for operation in self.planned_operations
        ]
        data["candidate_matches"] = list(self.candidate_matches)
        data["acceptance_criteria"] = list(self.acceptance_criteria)
        data["risks"] = list(self.risks)
        data["assumptions"] = list(self.assumptions)
        data["clarification_questions"] = list(self.clarification_questions)
        return data
