from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument


@dataclass(frozen=True)
class CompactBpmnContext:
    payload: dict[str, Any]
    process_alias_to_id: dict[str, str]


class CompactContextBuilder:
    """Build an ID-free BPMN catalogue for language-model interpretation."""

    def __init__(self, document: BpmnDocument):
        self.document = document

    def build(self, *, max_elements_per_process: int = 100) -> CompactBpmnContext:
        process_ids = [
            process_id
            for process_id in sorted(self.document.processes)
            if any(
                element.process_id == process_id
                for element in self.document.elements.values()
            )
        ]
        aliases = {
            f"process_{index}": process_id
            for index, process_id in enumerate(process_ids, start=1)
        }

        processes: list[dict[str, Any]] = []
        for alias, process_id in aliases.items():
            process = self.document.processes.get(process_id, {})
            elements = sorted(
                (
                    element
                    for element in self.document.elements.values()
                    if element.process_id == process_id
                ),
                key=lambda element: ((element.lane_name or ""), (element.name or ""), element.type),
            )
            lane_counts = Counter(element.lane_name or "unassigned" for element in elements)

            # Include empty lanes declared in the BPMN XML.
            for lane in self.document.lanes.values():
                if lane.get("process_id") != process_id:
                    continue

                lane_name = lane.get("name")
                if lane_name:
                    lane_counts.setdefault(str(lane_name), 0)

            catalogue = [
                {
                    "type": element.type,
                    "name": element.name,
                    "lane": element.lane_name,
                }
                for element in elements[:max_elements_per_process]
                if element.name
            ]
            processes.append(
                {
                    "alias": alias,
                    "participant_name": process.get("participant_name"),
                    "flow_node_count": len(elements),
                    "lanes": [
                        {"name": lane_name, "flow_node_count": count}
                        for lane_name, count in sorted(lane_counts.items())
                    ],
                    "elements": catalogue,
                    "catalogue_truncated": len(elements) > max_elements_per_process,
                }
            )

        return CompactBpmnContext(
            payload={
                "process_count": len(processes),
                "processes": processes,
                "rules": {
                    "identifiers_hidden": True,
                    "process_selection_uses_aliases": True,
                },
            },
            process_alias_to_id=aliases,
        )
