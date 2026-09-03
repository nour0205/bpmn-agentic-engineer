from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from bpmn_agentic_engineer.analysis import BpmnAnalyzer
from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.cli import _recommend, build_parser
from bpmn_agentic_engineer.recommendation.context import RecommendationContextBuilder
from bpmn_agentic_engineer.recommendation.models import RecommendationResult
from bpmn_agentic_engineer.recommendation.service import BpmnRecommendationService
from bpmn_agentic_engineer.recommendation.validator import RecommendationValidator
from scripts.evaluate_recommendations import aggregate, evaluate_case

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "data" / "bpmn" / "as_is" / "Détermination des besoins d'approvisionnement.bpmn"


def evidence_fixture():
    document = BpmnDocument(SOURCE)
    analysis = BpmnAnalyzer().analyze(SOURCE)
    finding = next(
        item
        for item in analysis.findings
        if item.code == "SEQUENTIAL_HUMAN_TASK_CHAIN" and len(item.element_ids) >= 3
    )
    elements = [document.elements[element_id] for element_id in finding.element_ids]
    payload = {
        "recommendations": [
            {
                "id": "rec_001",
                "category": "AUTOMATION",
                "title": "Automatiser la couverture",
                "problem": "Une séquence humaine combine export, calcul manuel et consolidation.",
                "evidence": [
                    {
                        "finding_code": finding.code,
                        "element_ids": list(finding.element_ids),
                        "reason": "Trois tâches humaines linéaires dans le même flux.",
                    }
                ],
                "recommendation": "Remplacer la séquence par une tâche de service.",
                "affected_elements": [
                    {
                        "element_id": item.id,
                        "name": item.name,
                        "type": item.type,
                        "process_id": item.process_id,
                        "lane": item.lane_name,
                    }
                    for item in elements
                ],
                "proposed_changes": [
                    {
                        "kind": "replacement_task",
                        "name": "Générer automatiquement la couverture",
                        "type": "serviceTask",
                        "lane": elements[0].lane_name,
                        "anchor_element_id": None,
                        "position": None,
                    }
                ],
                "suggested_operation": "replace_linear_task_sequence",
                "executable_by_current_engine": True,
                "confidence": "high",
                "impact": "high",
                "complexity": "medium",
                "assumptions": [],
            }
        ]
    }
    return document, analysis, finding, payload


def test_context_contains_only_as_is_evidence_and_goal() -> None:
    document, analysis, finding, _ = evidence_fixture()
    context = RecommendationContextBuilder().build(document, analysis, goal="Réduire le manuel")
    serialized = json.dumps(context, ensure_ascii=False)
    assert SOURCE.name in serialized
    assert finding.code in serialized
    assert context["goal"] == "Réduire le manuel"
    assert "dataset_manifest" not in serialized
    assert "data/bpmn/cible" not in serialized.replace("\\", "/")
    assert "expected_operation" not in serialized


def test_valid_recommendation_accepted_and_executable() -> None:
    document, analysis, _, payload = evidence_fixture()
    accepted, rejected = RecommendationValidator().validate(document, analysis, payload)
    assert not rejected
    assert accepted[0].executable_by_current_engine is True
    assert accepted[0].suggested_operation == "replace_linear_task_sequence"


@pytest.mark.parametrize(
    ("field", "value"), [("element_id", "missing"), ("process_id", "wrong"), ("lane", "wrong")]
)
def test_hallucinated_or_mismatched_affected_element_rejected(field: str, value: str) -> None:
    document, analysis, _, payload = evidence_fixture()
    payload["recommendations"][0]["affected_elements"][0][field] = value
    accepted, rejected = RecommendationValidator().validate(document, analysis, payload)
    assert not accepted
    assert rejected


def test_non_linear_sequence_is_not_marked_executable() -> None:
    document, analysis, _, payload = evidence_fixture()
    elements = payload["recommendations"][0]["affected_elements"]
    elements[0], elements[1] = elements[1], elements[0]
    accepted, rejected = RecommendationValidator().validate(document, analysis, payload)
    assert not rejected
    assert accepted[0].executable_by_current_engine is False


def test_duplicate_recommendations_are_deduplicated() -> None:
    document, analysis, _, payload = evidence_fixture()
    duplicate = json.loads(json.dumps(payload["recommendations"][0]))
    duplicate["id"] = "rec_002"
    duplicate["confidence"] = "medium"
    payload["recommendations"].append(duplicate)
    accepted, _ = RecommendationValidator().validate(document, analysis, payload)
    assert [item.id for item in accepted] == ["rec_001"]


def test_zero_recommendations_is_valid() -> None:
    document, analysis, _, _ = evidence_fixture()
    assert RecommendationValidator().validate(document, analysis, {"recommendations": []}) == (
        [],
        [],
    )


def test_service_is_reusable_and_does_not_modify_source() -> None:
    _, _, _, payload = evidence_fixture()
    before = SOURCE.read_bytes()

    class FakeBridge:
        def generate(self, context):
            assert context["source"]["filename"] == SOURCE.name
            return payload

    result = BpmnRecommendationService(bridge=FakeBridge()).recommend(SOURCE)
    assert len(result.recommendations) == 1
    assert SOURCE.read_bytes() == before


def test_malformed_qwen_output_fails_safely() -> None:
    class FakeBridge:
        def generate(self, context):
            return {"unexpected": []}

    with pytest.raises(ValueError, match="recommendations"):
        BpmnRecommendationService(bridge=FakeBridge()).recommend(SOURCE)


def test_cli_parser_supports_recommend_goal_and_json() -> None:
    args = build_parser().parse_args(
        ["recommend", str(SOURCE), "--goal", "Réduire les tâches manuelles", "--json"]
    )
    assert args.command == "recommend"
    assert args.goal == "Réduire les tâches manuelles"
    assert args.json_output is True


def test_cli_human_and_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, analysis, _, payload = evidence_fixture()
    document = BpmnDocument(SOURCE)
    recommendations, _ = RecommendationValidator().validate(document, analysis, payload)
    result = RecommendationResult(str(SOURCE), analysis.process_name, None, tuple(recommendations))

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        def recommend(self, file, goal=None):
            return result

    monkeypatch.setattr(
        "bpmn_agentic_engineer.recommendation.BpmnRecommendationService", FakeService
    )
    base = {
        "file": str(SOURCE),
        "goal": None,
        "show_low_confidence": False,
        "state_dir": ".state",
        "kaggle_kernel_ref": "x/y",
        "poll_interval": 0,
        "timeout": 1,
        "verbose": False,
    }
    assert _recommend(Namespace(**base, json_output=False)) == 0
    human = capsys.readouterr().out
    assert "BPMN OPTIMIZATION RECOMMENDATIONS" in human
    assert "Approve" not in human
    assert "Id_" not in human
    assert _recommend(Namespace(**base, json_output=True)) == 0
    assert json.loads(capsys.readouterr().out)["recommendation_count"] == 1


def test_evaluation_uses_structural_matching() -> None:
    manifest = json.loads((ROOT / "data/bpmn/dataset_manifest.json").read_text(encoding="utf-8"))
    case = next(item for item in manifest["cases"] if item["case_id"] == "process_3")
    _, analysis, _, payload = evidence_fixture()
    document = BpmnDocument(SOURCE)
    recommendations, _ = RecommendationValidator().validate(document, analysis, payload)
    report = evaluate_case(case, [item.to_dict() for item in recommendations])
    assert report["correct_detections"] == 1
    global_report = aggregate([report])["global"]
    assert global_report["recommendation_precision"] == 1.0


def test_production_recommendation_code_has_no_ground_truth_dependency() -> None:
    package = ROOT / "src" / "bpmn_agentic_engineer" / "recommendation"
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert "dataset_manifest" not in source
    assert "data/bpmn/cible" not in source.replace("\\", "/")
