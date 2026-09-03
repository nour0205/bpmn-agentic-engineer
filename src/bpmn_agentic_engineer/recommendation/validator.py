from __future__ import annotations

from itertools import pairwise
from typing import Any

from bpmn_agentic_engineer.analysis import BpmnAnalysisResult
from bpmn_agentic_engineer.bpmn import BpmnDocument

from .models import (
    CATEGORIES,
    LEVELS,
    OPERATIONS,
    ExistingElement,
    ProposedChange,
    Recommendation,
    RecommendationEvidence,
)
from .ranking import rank_recommendations

_ROOT_KEYS = {"recommendations"}
_REC_KEYS = {
    "id",
    "category",
    "title",
    "problem",
    "evidence",
    "recommendation",
    "affected_elements",
    "proposed_changes",
    "suggested_operation",
    "executable_by_current_engine",
    "confidence",
    "impact",
    "complexity",
    "assumptions",
}
_EVIDENCE_KEYS = {"finding_code", "element_ids", "reason"}
_ELEMENT_KEYS = {"element_id", "name", "type", "process_id", "lane"}
_CHANGE_KEYS = {"kind", "name", "type", "lane", "anchor_element_id", "position"}
_TASK_TYPES = {
    "task",
    "userTask",
    "manualTask",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "scriptTask",
    "businessRuleTask",
}


class RecommendationValidator:
    def validate(
        self,
        document: BpmnDocument,
        analysis: BpmnAnalysisResult,
        payload: dict[str, Any],
    ) -> tuple[list[Recommendation], list[str]]:
        if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
            raise ValueError("Qwen recommendation output must contain only 'recommendations'.")
        raw_items = payload["recommendations"]
        if not isinstance(raw_items, list):
            raise TypeError("recommendations must be an array.")
        accepted: list[Recommendation] = []
        rejected: list[str] = []
        for index, raw in enumerate(raw_items):
            try:
                accepted.append(self._one(document, analysis, raw))
            except (KeyError, TypeError, ValueError) as exc:
                rejected.append(f"recommendations[{index}]: {exc}")
        return self._deduplicate(accepted), rejected

    def _one(self, document, analysis, raw) -> Recommendation:
        self._exact_dict(raw, _REC_KEYS, "recommendation")
        for field in (
            "id",
            "category",
            "title",
            "problem",
            "recommendation",
            "suggested_operation",
            "confidence",
            "impact",
            "complexity",
        ):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ValueError(f"{field} must be a non-empty string")
        if raw["category"] not in CATEGORIES:
            raise ValueError("unknown category")
        if raw["suggested_operation"] not in OPERATIONS:
            raise ValueError("unknown suggested_operation")
        for field in ("confidence", "impact", "complexity"):
            if raw[field] not in LEVELS:
                raise ValueError(f"{field} must be high, medium, or low")
        if not isinstance(raw.get("executable_by_current_engine"), bool):
            raise TypeError("executable_by_current_engine must be boolean")
        evidence = self._evidence(analysis, raw.get("evidence"))
        elements = self._elements(document, raw.get("affected_elements"))
        changes = self._changes(document, raw.get("proposed_changes"))
        assumptions = raw.get("assumptions")
        if not isinstance(assumptions, list) or not all(
            isinstance(item, str) for item in assumptions
        ):
            raise ValueError("assumptions must be an array of strings")
        cited_ids = {item for citation in evidence for item in citation.element_ids}
        affected_ids = {item.element_id for item in elements}
        if affected_ids and not affected_ids.issubset(cited_ids):
            raise ValueError("every affected element must be supported by cited evidence")
        process_ids = {item.process_id for item in elements}
        if len(process_ids) > 1:
            raise ValueError("affected elements belong to different processes")
        operation = raw["suggested_operation"]
        executable = self._is_executable(document, operation, elements, changes)
        return Recommendation(
            id=raw["id"].strip(),
            category=raw["category"],
            title=raw["title"].strip(),
            problem=raw["problem"].strip(),
            evidence=evidence,
            recommendation=raw["recommendation"].strip(),
            affected_elements=elements,
            proposed_changes=changes,
            suggested_operation=operation,
            executable_by_current_engine=executable,
            confidence=raw["confidence"],
            impact=raw["impact"],
            complexity=raw["complexity"],
            assumptions=tuple(item.strip() for item in assumptions if item.strip()),
        )

    def _evidence(self, analysis, raw) -> tuple[RecommendationEvidence, ...]:
        if not isinstance(raw, list) or not raw:
            raise ValueError("at least one evidence item is required")
        findings = {(item.code, tuple(item.element_ids)) for item in analysis.findings}
        output = []
        for item in raw:
            self._exact_dict(item, _EVIDENCE_KEYS, "evidence")
            ids = item.get("element_ids")
            if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
                raise ValueError("evidence element_ids must be strings")
            key = (item.get("finding_code"), tuple(ids))
            if key not in findings:
                raise ValueError("evidence does not match a deterministic finding")
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("evidence reason is required")
            output.append(
                RecommendationEvidence(str(item["finding_code"]), tuple(ids), reason.strip())
            )
        return tuple(output)

    def _elements(self, document, raw) -> tuple[ExistingElement, ...]:
        if not isinstance(raw, list):
            raise TypeError("affected_elements must be an array")
        output = []
        for item in raw:
            self._exact_dict(item, _ELEMENT_KEYS, "affected element")
            element_id = item.get("element_id")
            if element_id not in document.elements:
                raise ValueError(f"unknown affected element: {element_id}")
            actual = document.elements[element_id]
            expected = {
                "name": actual.name,
                "type": actual.type,
                "process_id": actual.process_id,
                "lane": actual.lane_name,
            }
            for key, value in expected.items():
                if item.get(key) != value:
                    raise ValueError(f"affected element {element_id} has incorrect {key}")
            output.append(
                ExistingElement(
                    element_id, actual.name, actual.type, str(actual.process_id), actual.lane_name
                )
            )
        return tuple(output)

    def _changes(self, document, raw) -> tuple[ProposedChange, ...]:
        if not isinstance(raw, list):
            raise TypeError("proposed_changes must be an array")
        output = []
        lane_names = {lane.get("name") for lane in document.lanes.values()}
        for item in raw:
            self._exact_dict(item, _CHANGE_KEYS, "proposed change")
            if not isinstance(item.get("kind"), str) or not item["kind"].strip():
                raise ValueError("proposed change kind is required")
            if item.get("type") is not None and item["type"] not in _TASK_TYPES:
                raise ValueError("invalid proposed task type")
            if item.get("lane") is not None and item["lane"] not in lane_names:
                raise ValueError("unknown proposed destination lane")
            anchor = item.get("anchor_element_id")
            if anchor is not None and anchor not in document.elements:
                raise ValueError("unknown proposed change anchor")
            if item.get("position") not in {None, "before", "after"}:
                raise ValueError("position must be before, after, or null")
            output.append(ProposedChange(**item))
        return tuple(output)

    @staticmethod
    def _is_executable(document, operation, elements, changes) -> bool:
        ids = [item.element_id for item in elements]
        if operation == "analysis_only":
            return False
        if operation == "rename_element":
            return len(ids) == 1 and bool(changes and changes[0].name)
        if operation == "remove_element":
            return (
                len(ids) == 1
                and len(document.incoming[ids[0]]) == 1
                and len(document.outgoing[ids[0]]) == 1
            )
        if operation in {"insert_task_before", "insert_task_after"}:
            return bool(changes and changes[0].anchor_element_id and changes[0].name)
        if operation == "replace_linear_task_sequence":
            if len(ids) < 2 or not changes or not changes[0].name:
                return False
            return all(
                right in document.outgoing[left]
                and len(document.outgoing[left]) == 1
                and len(document.incoming[right]) == 1
                for left, right in pairwise(ids)
            )
        return False

    @staticmethod
    def _deduplicate(items: list[Recommendation]) -> list[Recommendation]:
        strongest = []
        for item in rank_recommendations(items):
            ids = {element.element_id for element in item.affected_elements}
            duplicate = False
            for kept in strongest:
                kept_ids = {element.element_id for element in kept.affected_elements}
                if (
                    item.category == kept.category
                    and item.suggested_operation == kept.suggested_operation
                    and (ids == kept_ids or (ids and ids.issubset(kept_ids)))
                ):
                    duplicate = True
                    break
            if not duplicate:
                strongest.append(item)
        return rank_recommendations(strongest)

    @staticmethod
    def _exact_dict(value, keys, label):
        if not isinstance(value, dict):
            raise TypeError(f"{label} must be an object")
        unknown = set(value) - keys
        missing = keys - set(value)
        if unknown or missing:
            raise ValueError(
                f"{label} fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
