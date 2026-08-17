from __future__ import annotations

from collections import Counter, deque
import re
import unicodedata
from typing import Any

from bpmn_agentic_engineer.bpmn.document import BpmnDocument
from bpmn_agentic_engineer.models import BpmnElement


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    punctuation_normalized = re.sub(r"[^\w]+", " ", without_accents.casefold())
    return " ".join(punctuation_normalized.split())


def _element_payload(element: BpmnElement) -> dict[str, Any]:
    return element.to_dict()


class ProcessInspector:
    def __init__(self, document: BpmnDocument):
        self.document = document

    def summary(self, include_elements: bool = True) -> dict[str, Any]:
        type_counts = Counter(element.type for element in self.document.elements.values())
        lane_counts = Counter(
            element.lane_name or element.lane_id or "unassigned"
            for element in self.document.elements.values()
        )
        start_events = [
            element.id for element in self.document.elements.values()
            if element.type == "startEvent"
        ]
        end_events = [
            element.id for element in self.document.elements.values()
            if element.type == "endEvent"
        ]

        payload: dict[str, Any] = {
            "file": str(self.document.path),
            "processes": list(self.document.processes.values()),
            "statistics": {
                "process_count": len(self.document.processes),
                "flow_node_count": len(self.document.elements),
                "sequence_flow_count": len(self.document.sequence_flows),
                "lane_count": len(self.document.lanes),
                "element_types": dict(sorted(type_counts.items())),
                "lane_assignments": dict(sorted(lane_counts.items())),
            },
            "start_events": start_events,
            "end_events": end_events,
        }
        if include_elements:
            payload["elements"] = [
                _element_payload(element)
                for element in sorted(self.document.elements.values(), key=lambda item: item.id)
            ]
            payload["sequence_flows"] = [
                flow.to_dict()
                for flow in sorted(self.document.sequence_flows.values(), key=lambda item: item.id)
            ]
        return payload

    def find_elements(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized_query = _normalize(query)
        if not normalized_query:
            raise ValueError("Search query cannot be empty.")
        query_tokens = set(normalized_query.split())

        scored: list[tuple[float, BpmnElement]] = []
        for element in self.document.elements.values():
            fields = {
                "id": _normalize(element.id),
                "name": _normalize(element.name),
                "type": _normalize(element.type),
                "lane": _normalize(element.lane_name or element.lane_id),
            }

            score = 0.0
            for field_name, field_value in fields.items():
                if not field_value:
                    continue
                weight = {"name": 5.0, "id": 3.0, "lane": 2.0, "type": 1.0}[field_name]
                if field_value == normalized_query:
                    score += 4.0 * weight
                elif normalized_query in field_value:
                    score += 2.0 * weight
                field_tokens = set(field_value.split())
                if query_tokens:
                    score += weight * len(query_tokens & field_tokens) / len(query_tokens)

            if score > 0:
                scored.append((score, element))

        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [
            {"score": round(score, 3), **_element_payload(element)}
            for score, element in scored[: max(1, limit)]
        ]

    def element_context(self, element_id: str) -> dict[str, Any]:
        element = self.document.element(element_id)
        predecessors = [
            _element_payload(self.document.elements[node_id])
            for node_id in self.document.incoming.get(element_id, [])
            if node_id in self.document.elements
        ]
        successors = [
            _element_payload(self.document.elements[node_id])
            for node_id in self.document.outgoing.get(element_id, [])
            if node_id in self.document.elements
        ]
        incoming_flows = [
            flow.to_dict()
            for flow in self.document.sequence_flows.values()
            if flow.target_ref == element_id
        ]
        outgoing_flows = [
            flow.to_dict()
            for flow in self.document.sequence_flows.values()
            if flow.source_ref == element_id
        ]
        return {
            "element": _element_payload(element),
            "predecessors": predecessors,
            "successors": successors,
            "incoming_sequence_flows": incoming_flows,
            "outgoing_sequence_flows": outgoing_flows,
        }

    def find_path(self, source_id: str, target_id: str) -> dict[str, Any]:
        self.document.element(source_id)
        self.document.element(target_id)

        queue: deque[list[str]] = deque([[source_id]])
        visited = {source_id}

        while queue:
            path = queue.popleft()
            current = path[-1]
            if current == target_id:
                return {
                    "found": True,
                    "source_id": source_id,
                    "target_id": target_id,
                    "node_ids": path,
                    "elements": [
                        _element_payload(self.document.elements[node_id])
                        for node_id in path
                    ],
                }
            for successor in self.document.outgoing.get(current, []):
                if successor in self.document.elements and successor not in visited:
                    visited.add(successor)
                    queue.append(path + [successor])

        return {
            "found": False,
            "source_id": source_id,
            "target_id": target_id,
            "node_ids": [],
            "elements": [],
        }
