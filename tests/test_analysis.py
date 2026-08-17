from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bpmn_agentic_engineer.analysis import BpmnAnalyzer

ROOT = Path(__file__).parents[1]
SIMPLE = ROOT / "tests" / "fixtures" / "simple_process.bpmn"
AS_IS = ROOT / "outputs" / "linkedin_demo" / "input" / "as_is.bpmn"


def codes(result):
    return [finding.code for finding in result.findings]


def write_process(tmp_path: Path, nodes: list[tuple[str, str, str, str]], edges: list[tuple[str, str]]) -> Path:
    lane_nodes: dict[str, list[str]] = {}
    for identifier, _, _, lane in nodes:
        lane_nodes.setdefault(lane, []).append(identifier)
    lanes = "".join(f'<bpmn:lane id="L{i}" name="{lane}">' + "".join(f"<bpmn:flowNodeRef>{n}</bpmn:flowNodeRef>" for n in ids) + "</bpmn:lane>" for i, (lane, ids) in enumerate(lane_nodes.items()))
    elements = "".join(f'<bpmn:{kind} id="{identifier}" name="{name}"/>' for identifier, kind, name, _ in nodes)
    flows = "".join(f'<bpmn:sequenceFlow id="F{i}" sourceRef="{source}" targetRef="{target}"/>' for i, (source, target) in enumerate(edges))
    content = f'<?xml version="1.0" encoding="UTF-8"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"><bpmn:process id="P" name="Test"><bpmn:laneSet id="LS">{lanes}</bpmn:laneSet>{elements}{flows}</bpmn:process></bpmn:definitions>'
    target = tmp_path / "process.bpmn"
    target.write_text(content, encoding="utf-8")
    return target


def test_graph_and_core_counts() -> None:
    result = BpmnAnalyzer().analyze(SIMPLE)
    assert result.graph_summary["nodes"] == 6
    assert result.graph_summary["edges"] == 5
    assert result.metrics["total_flow_nodes"] == 6
    assert result.metrics["sequence_flows"] == 5


def test_existing_lane_resolution_is_reused() -> None:
    result = BpmnAnalyzer().analyze(SIMPLE)
    assert result.metrics["lanes"] == 2
    assert {lane["name"] for lane in result.lanes} == {"Finance", "Requesting department"}


def test_linkedin_human_chain_and_lexical_signals() -> None:
    result = BpmnAnalyzer().analyze(AS_IS)
    chain = next(f for f in result.findings if f.code == "SEQUENTIAL_HUMAN_TASK_CHAIN" and "Calculer manuellement la couverture de stock" in f.element_names)
    assert chain.metrics["length"] >= 3
    assert any(f.code == "DATA_ENTRY_SIGNAL" and "Exporter les résultats" in f.element_names[0] for f in result.findings)
    assert any(f.code == "MANUAL_COMMUNICATION_SIGNAL" and "e-mail" in f.element_names[0] for f in result.findings)
    assert any(f.code == "CONTROL_ACTIVITY_SIGNAL" and "e-mail" in f.element_names[0] for f in result.findings)


def test_duplicate_exact_labels(tmp_path: Path) -> None:
    path = write_process(tmp_path, [("A", "userTask", "Même tâche", "X"), ("B", "userTask", " même  tâche ", "Y")], [("A", "B")])
    finding = next(f for f in BpmnAnalyzer().analyze(path).findings if f.code == "DUPLICATE_LABEL")
    assert finding.metrics["occurrences"] == 2


def test_lane_handoff_and_back_and_forth(tmp_path: Path) -> None:
    path = write_process(tmp_path, [("A", "userTask", "A", "Procurement"), ("B", "userTask", "B", "Finance"), ("C", "userTask", "C", "Procurement")], [("A", "B"), ("B", "C")])
    result = BpmnAnalyzer().analyze(path)
    assert codes(result).count("LANE_HANDOFF") == 2
    assert "LANE_BACK_AND_FORTH" in codes(result)


@pytest.mark.parametrize(("name", "expected"), [("Saisir les données", "DATA_ENTRY_SIGNAL"), ("Vérifier le contrat", "CONTROL_ACTIVITY_SIGNAL"), ("Envoyer par email", "MANUAL_COMMUNICATION_SIGNAL")])
def test_lexical_detectors(tmp_path: Path, name: str, expected: str) -> None:
    path = write_process(tmp_path, [("A", "userTask", name, "Lane")], [])
    assert expected in codes(BpmnAnalyzer().analyze(path))


def test_cycle_detection_is_safe(tmp_path: Path) -> None:
    path = write_process(tmp_path, [("A", "task", "A", "Lane"), ("B", "task", "B", "Lane")], [("A", "B"), ("B", "A")])
    result = BpmnAnalyzer().analyze(path)
    assert result.metrics["cycles"] == 1
    assert result.metrics["longest_structural_path"] == 2
    assert "CYCLE" in codes(result)


def test_acyclic_longest_structural_path(tmp_path: Path) -> None:
    path = write_process(tmp_path, [(str(i), "task", str(i), "Lane") for i in range(4)], [("0", "1"), ("1", "2"), ("2", "3")])
    result = BpmnAnalyzer().analyze(path)
    assert result.metrics["cycles"] == 0
    assert result.metrics["longest_structural_path"] == 4
    assert result.metrics["longest_linear_task_chain"] == 4


def test_implicit_start_is_supported(tmp_path: Path) -> None:
    path = write_process(tmp_path, [("A", "userTask", "Begin", "Lane"), ("B", "endEvent", "End", "Lane")], [("A", "B")])
    result = BpmnAnalyzer().analyze(path)
    assert result.metrics["start_like_nodes"] == 1
    assert result.metrics["unreachable_nodes"] == 0


def test_result_is_json_serializable() -> None:
    payload = BpmnAnalyzer().analyze(SIMPLE).to_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False))["metrics"]["total_flow_nodes"] == 6


def test_analysis_is_read_only() -> None:
    before = hashlib.sha256(AS_IS.read_bytes()).digest()
    BpmnAnalyzer().analyze(AS_IS)
    assert hashlib.sha256(AS_IS.read_bytes()).digest() == before


def test_real_bizagi_document_is_supported() -> None:
    source = next((ROOT / "data" / "bpmn").glob("Gestion des contrats.bpmn"))
    result = BpmnAnalyzer().analyze(source)
    assert result.metrics["total_flow_nodes"] > 0 and result.metrics["lanes"] > 0
    assert "DUPLICATE_LABEL" in codes(result)
