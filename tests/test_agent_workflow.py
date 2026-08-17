from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langgraph.checkpoint.sqlite")

from bpmn_agentic_engineer.agent import AgentService
from bpmn_agentic_engineer.bpmn import BpmnDocument


FIXTURES = Path(__file__).parent / "fixtures"
EXECUTION = FIXTURES / "execution_process.bpmn"
AMBIGUOUS = FIXTURES / "ambiguous_processes.bpmn"


def test_agent_pauses_for_approval_then_executes_exact_plan(tmp_path: Path) -> None:
    service = AgentService(tmp_path / "state")
    output = tmp_path / "modified.bpmn"

    started = service.start(
        EXECUTION,
        "Ajouter une tâche après une activité",
        target_element_id="Task_1",
        new_name="Valider le dossier d'appel d'offres",
        output_path=output,
    )

    assert started["status"] == "waiting_for_approval"
    assert started["interrupt"]["kind"] == "approval"
    checksum = started["plan_checksum"]

    completed = service.resume(started["run_id"], approved=True)

    assert completed["status"] == "completed"
    assert completed["plan_checksum"] == checksum
    assert completed["execution_result"]["status"] == "execution_succeeded"
    assert completed["validation"]["error_count"] == 0
    assert output.exists()

    modified = BpmnDocument(output)
    assert any(
        element.name == "Valider le dossier d'appel d'offres"
        for element in modified.elements.values()
    )


def test_agent_clarification_resumes_to_same_approval_workflow(tmp_path: Path) -> None:
    service = AgentService(tmp_path / "state")

    started = service.start(
        AMBIGUOUS,
        'Rename "Review request" to "Validate request"',
    )
    assert started["status"] == "needs_clarification"
    assert started["interrupt"]["kind"] == "clarification"

    clarified = service.resume(started["run_id"], process_id="Process_B")
    assert clarified["status"] == "waiting_for_approval"
    assert clarified["selected_target"]["id"] == "Task_B"
    assert clarified["interrupt"]["kind"] == "approval"


def test_rejected_plan_never_creates_output(tmp_path: Path) -> None:
    service = AgentService(tmp_path / "state")
    output = tmp_path / "rejected.bpmn"

    started = service.start(
        EXECUTION,
        "Ajouter une tâche après une activité",
        target_element_id="Task_1",
        new_name="Review dossier",
        output_path=output,
    )
    rejected = service.resume(started["run_id"], approved=False)

    assert rejected["status"] == "cancelled"
    assert not output.exists()


def test_agent_status_survives_service_recreation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    first_service = AgentService(state_dir)
    started = first_service.start(
        EXECUTION,
        "Ajouter une tâche après une activité",
        target_element_id="Task_1",
        new_name="Review dossier",
    )

    second_service = AgentService(state_dir)
    persisted = second_service.status(started["run_id"])

    assert persisted["run_id"] == started["run_id"]
    assert persisted["status"] == "waiting_for_approval"
    assert persisted["plan_checksum"] == started["plan_checksum"]
