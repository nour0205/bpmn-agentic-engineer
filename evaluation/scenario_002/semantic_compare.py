from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unicodedata

from bpmn_agentic_engineer.bpmn import BpmnDocument


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "evaluation" / "scenario_002" / "reference" / "cible.bpmn"
GENERATED = ROOT / "evaluation" / "scenario_002" / "generated" / "scenario_002_final.bpmn"
OUTPUT = ROOT / "evaluation" / "scenario_002" / "results" / "final_semantic_comparison.json"


def normalize(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def node_key(element: object) -> tuple[str, str, str]:
    return (element.type, normalize(element.name), normalize(element.lane_name))


def node_payload(key: tuple[str, str, str], count: int) -> dict[str, object]:
    return {"bpmn_type": key[0], "normalized_name": key[1], "lane": key[2], "count": count}


def nodes(document: BpmnDocument) -> Counter[tuple[str, str, str]]:
    return Counter(node_key(element) for element in document.elements.values())


def flows(
    document: BpmnDocument,
) -> Counter[tuple[tuple[str, str, str], tuple[str, str, str]]]:
    return Counter(
        (
            node_key(document.elements[flow.source_ref]),
            node_key(document.elements[flow.target_ref]),
        )
        for flow in document.sequence_flows.values()
    )


def flow_payload(
    key: tuple[tuple[str, str, str], tuple[str, str, str]], count: int
) -> dict[str, object]:
    return {
        "source": node_payload(key[0], 1),
        "target": node_payload(key[1], 1),
        "count": count,
    }


def percentage(matched: int, total: int) -> float:
    return round(100.0 * matched / total, 2) if total else 100.0


def main() -> None:
    reference = BpmnDocument(REFERENCE)
    generated = BpmnDocument(GENERATED)
    reference_nodes = nodes(reference)
    generated_nodes = nodes(generated)
    reference_flows = flows(reference)
    generated_flows = flows(generated)

    missing_nodes = reference_nodes - generated_nodes
    extra_nodes = generated_nodes - reference_nodes
    missing_flows = reference_flows - generated_flows
    extra_flows = generated_flows - reference_flows

    generated_by_name = {
        normalize(element.name): element for element in generated.elements.values()
    }
    wrong_types: list[dict[str, str | None]] = []
    wrong_lanes: list[dict[str, str | None]] = []
    correct_types = 0
    correct_lanes = 0
    for element in reference.elements.values():
        counterpart = generated_by_name.get(normalize(element.name))
        if counterpart is not None and counterpart.type == element.type:
            correct_types += 1
        elif counterpart is not None:
            wrong_types.append(
                {
                    "name": element.name,
                    "reference_type": element.type,
                    "generated_type": counterpart.type,
                }
            )
        if counterpart is not None and normalize(counterpart.lane_name) == normalize(element.lane_name):
            correct_lanes += 1
        elif counterpart is not None:
            wrong_lanes.append(
                {
                    "name": element.name,
                    "reference_lane": element.lane_name,
                    "generated_lane": counterpart.lane_name,
                }
            )

    matched_nodes = sum((reference_nodes & generated_nodes).values())
    matched_flows = sum((reference_flows & generated_flows).values())
    result = {
        "comparison": "semantic_id_and_di_independent",
        "node_identity": ["bpmn_type", "normalized_visible_name", "normalized_lane_name"],
        "flow_identity": ["semantic_source_identity", "semantic_target_identity"],
        "reference_flow_node_count": len(reference.elements),
        "generated_flow_node_count": len(generated.elements),
        "reference_sequence_flow_count": len(reference.sequence_flows),
        "generated_sequence_flow_count": len(generated.sequence_flows),
        "missing_semantic_nodes": [node_payload(key, count) for key, count in sorted(missing_nodes.items())],
        "extra_semantic_nodes": [node_payload(key, count) for key, count in sorted(extra_nodes.items())],
        "wrong_bpmn_types": wrong_types,
        "wrong_lane_assignments": wrong_lanes,
        "missing_semantic_flows": [flow_payload(key, count) for key, count in sorted(missing_flows.items())],
        "extra_semantic_flows": [flow_payload(key, count) for key, count in sorted(extra_flows.items())],
        "semantic_node_match_percentage": percentage(matched_nodes, len(reference.elements)),
        "semantic_flow_match_percentage": percentage(matched_flows, len(reference.sequence_flows)),
        "bpmn_type_accuracy": percentage(correct_types, len(reference.elements)),
        "lane_assignment_accuracy": percentage(correct_lanes, len(reference.elements)),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
