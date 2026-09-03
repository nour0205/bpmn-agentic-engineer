from __future__ import annotations

from typing import Any

from bpmn_agentic_engineer.analysis import BpmnAnalysisResult
from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector


class RecommendationContextBuilder:
    """Build compact evidence derived exclusively from one AS-IS BPMN."""

    def build(
        self,
        document: BpmnDocument,
        analysis: BpmnAnalysisResult,
        *,
        goal: str | None = None,
    ) -> dict[str, Any]:
        inspector = ProcessInspector(document)
        finding_payloads = []
        structure: dict[str, Any] = {}
        involved_ids: set[str] = set()
        for finding in analysis.findings:
            involved_ids.update(finding.element_ids)
            finding_payloads.append(
                {
                    "finding_code": finding.code,
                    "category": finding.category,
                    "severity": finding.severity,
                    "title": finding.title,
                    "evidence": finding.evidence,
                    "element_ids": list(finding.element_ids),
                    "element_names": list(finding.element_names),
                    "lanes": list(finding.lanes),
                    "metrics": finding.metrics,
                }
            )
        for element_id in sorted(involved_ids):
            if element_id in document.elements:
                context = inspector.element_context(element_id)
                element = context["element"]
                structure[element_id] = {
                    "element": {
                        "id": element["id"],
                        "type": element["type"],
                        "name": element["name"],
                        "process_id": element["process_id"],
                        "lane": element["lane_name"],
                    },
                    "predecessor_ids": [item["id"] for item in context["predecessors"]],
                    "successor_ids": [item["id"] for item in context["successors"]],
                }
        metric_names = {
            "total_flow_nodes",
            "sequence_flows",
            "tasks",
            "user_tasks",
            "service_tasks",
            "manual_tasks",
            "gateways",
            "lanes",
            "lane_handoffs",
            "cycles",
            "longest_structural_path",
            "longest_linear_task_chain",
        }
        return {
            "schema_version": "1.0",
            "source": {"filename": document.path.name},
            "goal": " ".join(goal.split()) if goal else None,
            "processes": [
                {
                    "id": process["id"],
                    "name": process["name"],
                    "participant_name": process["participant_name"],
                }
                for process in document.processes.values()
            ],
            "lanes": [
                {"name": lane["name"], "process_id": lane["process_id"]} for lane in analysis.lanes
            ],
            "summary": {
                "metrics": {
                    key: value for key, value in analysis.metrics.items() if key in metric_names
                },
                "graph": {
                    "nodes": analysis.graph_summary["nodes"],
                    "edges": analysis.graph_summary["edges"],
                    "cycle_count": analysis.graph_summary["cycle_count"],
                },
                "validation": {
                    "valid_for_agentic_editing": analysis.validation_summary[
                        "valid_for_agentic_editing"
                    ],
                    "error_count": analysis.validation_summary["error_count"],
                },
            },
            "findings": finding_payloads,
            "local_structure": structure,
            "engine_capabilities": {
                "supported_operations": [
                    "insert_task_before",
                    "insert_task_after",
                    "rename_element",
                    "remove_element",
                    "replace_linear_task_sequence",
                ],
                "analysis_only_examples": ["POTENTIAL_PARALLELIZATION"],
            },
        }
