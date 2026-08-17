from pathlib import Path

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.planning.grounding import ElementGrounder

ROOT = Path(__file__).parents[1]
BASELINE_V002 = (
    ROOT / "outputs" / "full_regression_appel_offres" / "input" / "generated"
    / "baseline_v002.bpmn"
)
TARGET_ID = "Id_1b6a9ad8-fe94-44a6-ae3d-da5152d4469d"


def grounder() -> ElementGrounder:
    document = BpmnDocument(BASELINE_V002)
    return ElementGrounder(document, ProcessInspector(document))


def test_sous_processus_descriptor_resolves_call_activity_anchor() -> None:
    result = grounder().ground(
        target_query=(
            "sous-processus Sélection du Fournisseur et lancement des commandes"
        )
    )
    assert result.status == "resolved"
    assert result.selected is not None
    assert result.selected.id == TARGET_ID
    assert result.selected.type == "callActivity"


def test_insert_before_call_activity_uses_lane_for_new_task_not_anchor_filter() -> None:
    document = BpmnDocument(BASELINE_V002)
    plan = ChangePlanner(document, ProcessInspector(document)).plan(
        "Ajouter une validation avant le sous-processus sélection fournisseur.",
        operation="insert_task_before",
        target_query=(
            "sous-processus Sélection du Fournisseur et lancement des commandes"
        ),
        new_name="Valider le tableau comparatif des offres",
        new_bpmn_type="userTask",
        lane_name="Direction d'Approvisionnement",
    )
    assert plan["status"] == "ready_for_approval"
    assert plan["selected_target"]["id"] == TARGET_ID
    add_task = plan["planned_operations"][0]
    reconnect = plan["planned_operations"][-1]
    assert add_task["parameters"]["lane_name"] == "Direction d'Approvisionnement"
    assert reconnect["parameters"]["target_ref"] == TARGET_ID
