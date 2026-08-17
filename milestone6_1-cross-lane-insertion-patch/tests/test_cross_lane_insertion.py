from pathlib import Path

from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner


FIXTURE = Path(__file__).parent / "fixtures" / "scenario_001_step_01_merged.bpmn"


def test_insert_user_task_before_anchor_in_another_lane(tmp_path):
    document = BpmnDocument(FIXTURE)
    plan = ChangePlanner(document).plan(
        "Ajoute l'activité « Effectuer une analyse financiére des simulations » "
        "avant « Choisir la simulation (solution) optimale », dans le couloir "
        "Direction Financiére.",
        operation="insert_task_before",
        target_query="Choisir la simulation (solution) optimale",
        new_name="Effectuer une analyse financiére des simulations",
        lane_name="Direction Financiére",
        new_bpmn_type="userTask",
    )

    assert plan["status"] == "ready_for_approval"
    assert plan["selected_target"]["name"] == "Choisir la simulation (solution) optimale"
    assert plan["selected_target"]["lane_name"] == "Direction d'Approvisionnement"

    add_task = next(
        operation
        for operation in plan["planned_operations"]
        if operation["operation"] == "add_task"
    )
    assert add_task["parameters"]["lane_name"] == "Direction Financiére"
    assert add_task["parameters"]["bpmn_type"] == "userTask"

    output = tmp_path / "step_02_financial_analysis.bpmn"
    result = BpmnPlanExecutor().execute(plan, output, approved=True)
    assert result["status"] == "execution_succeeded"

    generated = BpmnDocument(output)
    matches = [
        element
        for element in generated.elements.values()
        if element.name == "Effectuer une analyse financiére des simulations"
    ]
    assert len(matches) == 1
    inserted = matches[0]
    assert inserted.type == "userTask"
    assert inserted.lane_name == "Direction Financiére"

    predecessor_names = {
        generated.elements[node_id].name
        for node_id in generated.incoming[inserted.id]
    }
    successor_names = {
        generated.elements[node_id].name
        for node_id in generated.outgoing[inserted.id]
    }
    assert "Génération automatique de la couverture de stock relatif à chaque simulation (Autonomie)" in predecessor_names
    assert "Choisir la simulation (solution) optimale" in successor_names
