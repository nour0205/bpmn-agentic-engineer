from __future__ import annotations

from pathlib import Path

import pytest

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


FIXTURE = Path(__file__).parent / "fixtures" / "execution_process.bpmn"


def _plan() -> dict:
    document = BpmnDocument(FIXTURE)
    return ChangePlanner(document, ProcessInspector(document)).plan(
        "Ajouter une tâche après une activité",
        target_element_id="Task_1",
        new_name="Valider le dossier d'appel d'offres",
    )


def test_execute_approved_plan_on_new_file(tmp_path: Path) -> None:
    plan = _plan()
    assert plan["status"] == "ready_for_approval"
    assert plan["source_sha256"]
    assert plan["plan_checksum"]

    output = tmp_path / "modified.bpmn"
    result = BpmnPlanExecutor().execute(plan, output, approved=True)

    assert result["status"] == "execution_succeeded"
    assert result["source_file_unchanged"] is True
    assert output.exists()
    assert result["validation"]["error_count"] == 0

    modified = BpmnDocument(output)
    matches = [
        element
        for element in modified.elements.values()
        if element.name == "Valider le dossier d'appel d'offres"
    ]
    assert len(matches) == 1
    new_task = matches[0]
    assert new_task.process_id == "Process_1"
    assert new_task.lane_name == "SPCM"
    assert modified.outgoing["Task_1"] == [new_task.id]
    assert modified.outgoing[new_task.id] == ["Task_2"]
    assert BasicValidator(modified).validate()["valid_for_agentic_editing"] is True


def test_execution_requires_approval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit approval"):
        BpmnPlanExecutor().execute(
            _plan(),
            tmp_path / "not-approved.bpmn",
            approved=False,
        )


def test_execution_rejects_tampered_plan(tmp_path: Path) -> None:
    plan = _plan()
    plan["planned_operations"][0]["parameters"]["name"] = "Tampered"

    with pytest.raises(ValueError, match="checksum"):
        BpmnPlanExecutor().execute(
            plan,
            tmp_path / "tampered.bpmn",
            approved=True,
        )


def test_execution_never_overwrites_source() -> None:
    with pytest.raises(ValueError, match="different from the source"):
        BpmnPlanExecutor().execute(_plan(), FIXTURE, approved=True)
