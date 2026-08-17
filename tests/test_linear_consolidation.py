from __future__ import annotations

from pathlib import Path

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.llm.schema import LlmInterpretation
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


FIXTURE = Path(__file__).parent / "fixtures" / "scenario_001_as_is_revised.bpmn"
SOURCE_NAMES = [
    "Exporter les résultats des simulations vers un fichier Excel",
    "Calculer manuellement la couverture de stock",
    "Consolider les résultats de couverture de stock",
]
NEW_NAME = (
    "Génération automatique de la couverture de stock relatif "
    "à chaque simulation (Autonomie)"
)


def _plan() -> dict:
    document = BpmnDocument(FIXTURE)
    return ChangePlanner(document, ProcessInspector(document)).plan(
        "Consolider les trois activités manuelles en une tâche de service.",
        operation="replace_linear_task_sequence",
        source_queries=SOURCE_NAMES,
        new_name=NEW_NAME,
        new_bpmn_type="serviceTask",
        lane_name="Direction d'Approvisionnement",
    )


def test_llm_schema_accepts_linear_replacement() -> None:
    result = LlmInterpretation.from_dict(
        {
            "schema_version": "1.1",
            "operation": "replace_linear_task_sequence",
            "target_query": None,
            "source_queries": SOURCE_NAMES,
            "new_name": NEW_NAME,
            "new_bpmn_type": "serviceTask",
            "lane_name": "Direction d'Approvisionnement",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 0.95,
        },
        allowed_process_aliases={"process_1"},
    )
    assert result.source_queries == tuple(SOURCE_NAMES)
    assert result.new_bpmn_type == "serviceTask"


def test_planner_builds_safe_linear_replacement() -> None:
    plan = _plan()
    assert plan["status"] == "ready_for_approval"
    assert plan["requires_approval"] is True
    assert [
        item["name"] for item in plan["selected_target"]["sequence"]
    ] == SOURCE_NAMES
    operations = [item["operation"] for item in plan["planned_operations"]]
    assert operations.count("remove_sequence_flow") == 4
    assert operations.count("remove_element") == 3
    assert operations.count("add_task") == 1
    assert operations.count("add_sequence_flow") == 2
    add_task = next(
        item for item in plan["planned_operations"] if item["operation"] == "add_task"
    )
    assert add_task["parameters"]["bpmn_type"] == "serviceTask"


def test_executor_replaces_sequence_and_updates_diagram(tmp_path: Path) -> None:
    plan = _plan()
    output = tmp_path / "merged.bpmn"
    result = BpmnPlanExecutor().execute(plan, output, approved=True)
    assert result["status"] == "execution_succeeded"

    document = BpmnDocument(output)
    matching = [element for element in document.elements.values() if element.name == NEW_NAME]
    assert len(matching) == 1
    replacement = matching[0]
    assert replacement.type == "serviceTask"
    assert replacement.lane_name == "Direction d'Approvisionnement"
    assert all(
        element.name not in SOURCE_NAMES for element in document.elements.values()
    )
    context = ProcessInspector(document).element_context(replacement.id)
    assert len(context["predecessors"]) == 1
    assert len(context["successors"]) == 1
    assert document.shapes.get(replacement.id)
    assert BasicValidator(document).validate()["valid_for_agentic_editing"] is True


def test_planner_rejects_non_consecutive_selection() -> None:
    document = BpmnDocument(FIXTURE)
    plan = ChangePlanner(document, ProcessInspector(document)).plan(
        "Replace two unrelated tasks.",
        operation="replace_linear_task_sequence",
        source_queries=[
            SOURCE_NAMES[0],
            "Générer le programme d'approvisionnement",
        ],
        new_name="Activité consolidée",
        new_bpmn_type="serviceTask",
    )
    assert plan["status"] == "requires_clarification"
    assert plan["requires_approval"] is False
