from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator
from scripts.build_as_is_dataset import SUPPORTED_OPERATIONS, _semantic_signature, build_dataset

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "data" / "bpmn" / "dataset_manifest.json"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_dataset_pairs_validate_and_cible_checksums_match() -> None:
    manifest = _manifest()
    assert len(manifest["cases"]) == 6
    for case in manifest["cases"]:
        as_is = ROOT / case["as_is"]
        cible = ROOT / case["cible"]
        assert as_is.exists() and cible.exists()
        assert _hash(cible) == case["cible_sha256"]
        assert _hash(as_is) == case["as_is_sha256"]
        assert _hash(as_is) != _hash(cible)
        assert BasicValidator(BpmnDocument(as_is)).validate()["error_count"] == 0
        assert BasicValidator(BpmnDocument(cible)).validate()["error_count"] == 0
        assert 2 <= len(case["introduced_issues"]) <= 4
        assert case["intentional_differences"] == len(case["introduced_issues"])
        assert case["unexplained_differences"] == 0


def test_dataset_has_no_cross_process_flows() -> None:
    for case in _manifest()["cases"]:
        document = BpmnDocument(ROOT / case["as_is"])
        for flow in document.sequence_flows.values():
            source = document.elements.get(flow.source_ref)
            target = document.elements.get(flow.target_ref)
            if source and target:
                assert source.process_id == target.process_id == flow.process_id


def test_every_issue_plans_and_executes_with_current_engine(tmp_path: Path) -> None:
    for case in _manifest()["cases"]:
        as_is_path = ROOT / case["as_is"]
        cible = BpmnDocument(ROOT / case["cible"])
        for issue in case["introduced_issues"]:
            operation = issue["expected_operation"]
            assert operation in SUPPORTED_OPERATIONS
            document = BpmnDocument(as_is_path)
            hints: dict = {"operation": operation, "process_id": case["process_id"]}
            if operation == "remove_element":
                hints["target_element_id"] = issue["as_is_elements"][0]
            elif operation == "rename_element":
                target = cible.elements[issue["cible_element"]]
                hints.update(target_element_id=target.id, new_name=target.name)
            elif operation in {"insert_task_before", "insert_task_after"}:
                hints.update(
                    target_element_id=issue["restore_anchor"],
                    new_name=issue["restore_name"],
                    new_bpmn_type="userTask",
                    lane_name=issue["lane"],
                )
            else:
                target = cible.elements[issue["cible_element"]]
                hints.update(
                    source_queries=[document.elements[item].name for item in issue["as_is_elements"]],
                    new_name=target.name,
                    new_bpmn_type=target.type,
                    lane_name=target.lane_name,
                )
            plan = ChangePlanner(document, ProcessInspector(document)).plan(
                "Correction déterministe du cas de référence.", **hints
            )
            assert plan["status"] == "ready_for_approval", (case["case_id"], issue, plan)
            output = tmp_path / f"{case['case_id']}_{issue['id']}.bpmn"
            result = BpmnPlanExecutor().execute(plan, output, approved=True)
            assert result["status"] == "execution_succeeded"
            assert result["validation"]["error_count"] == 0


def test_generator_is_idempotent_and_never_changes_cible() -> None:
    before_cible = {path.name: _hash(path) for path in (ROOT / "data/bpmn/cible").glob("*.bpmn")}
    build_dataset()
    first_as_is = {
        path.name: _semantic_signature(BpmnDocument(path))
        for path in (ROOT / "data/bpmn/as_is").glob("*.bpmn")
    }
    build_dataset()
    second_as_is = {
        path.name: _semantic_signature(BpmnDocument(path))
        for path in (ROOT / "data/bpmn/as_is").glob("*.bpmn")
    }
    after_cible = {path.name: _hash(path) for path in (ROOT / "data/bpmn/cible").glob("*.bpmn")}
    assert before_cible == after_cible
    assert first_as_is == second_as_is


def test_process_3_three_changes_accumulate_into_one_valid_final(tmp_path: Path) -> None:
    case = next(case for case in _manifest()["cases"] if case["case_id"] == "process_3")
    current = ROOT / case["as_is"]
    cible = BpmnDocument(ROOT / case["cible"])
    source_hash = _hash(current)
    for index, issue in enumerate(case["introduced_issues"], 1):
        document = BpmnDocument(current)
        operation = issue["expected_operation"]
        hints: dict = {"operation": operation, "process_id": case["process_id"]}
        if operation == "remove_element":
            hints["target_element_id"] = issue["as_is_elements"][0]
        elif operation == "insert_task_before":
            hints.update(
                target_element_id=issue["restore_anchor"],
                new_name=issue["restore_name"],
                new_bpmn_type="userTask",
                lane_name=issue["lane"],
            )
        else:
            target = cible.elements[issue["cible_element"]]
            hints.update(
                source_queries=[document.elements[item].name for item in issue["as_is_elements"]],
                new_name=target.name,
                new_bpmn_type=target.type,
                lane_name=target.lane_name,
            )
        plan = ChangePlanner(document, ProcessInspector(document)).plan("Correction", **hints)
        assert plan["status"] == "ready_for_approval"
        next_path = tmp_path / ("final.bpmn" if index == 3 else f"working_{index}.bpmn")
        result = BpmnPlanExecutor().execute(plan, next_path, approved=True)
        assert result["status"] == "execution_succeeded"
        current = next_path
    assert _hash(ROOT / case["as_is"]) == source_hash
    final = BpmnDocument(current)
    assert BasicValidator(final).validate()["error_count"] == 0
    expected_names = {
        cible.elements[case["introduced_issues"][0]["cible_element"]].name,
        case["introduced_issues"][1]["restore_name"],
    }
    changed = [element for element in final.elements.values() if element.name in expected_names]
    assert {element.name for element in changed} == expected_names
    assert {element.process_id for element in changed} == {case["process_id"]}
    redundant_id = case["introduced_issues"][2]["as_is_elements"][0]
    assert redundant_id not in final.elements


def test_ground_truth_is_not_imported_by_production_agent() -> None:
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "bpmn_agentic_engineer").rglob("*.py")
    )
    assert "dataset_manifest" not in production
    assert "data/bpmn/cible" not in production.replace("\\", "/")
