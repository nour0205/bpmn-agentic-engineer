from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisFinding:
    code: str
    category: str
    title: str
    description: str
    severity: str = "info"
    confidence: float = 1.0
    element_ids: tuple[str, ...] = field(default_factory=tuple)
    element_names: tuple[str, ...] = field(default_factory=tuple)
    lanes: tuple[str, ...] = field(default_factory=tuple)
    evidence: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BpmnAnalysisResult:
    source_path: str
    process_name: str | None
    metrics: dict[str, int]
    lanes: tuple[dict[str, Any], ...]
    graph_summary: dict[str, Any]
    findings: tuple[AnalysisFinding, ...]
    validation_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [item.to_dict() for item in self.findings]
        return data
