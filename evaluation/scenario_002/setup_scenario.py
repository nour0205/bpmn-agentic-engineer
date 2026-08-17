from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "bpmn" / "Suivi des commandes.bpmn"
REFERENCE = ROOT / "evaluation" / "scenario_002" / "reference" / "cible.bpmn"
AS_IS = ROOT / "evaluation" / "scenario_002" / "input" / "as_is.bpmn"

ORIGINAL_RENAME = "Transmettre la lettre de relance au Fournisseur via le portail et par mail"
DEGRADED_RENAME = "Archiver la lettre de relance sans la transmettre au Fournisseur"
REMOVED_TASK = "Valider la lettre de relance"
INSERT_AFTER = "Communication d'une nouvelle date de réception de la part du Fournisseur sur le portail"
ARTIFICIAL_TASK = "Saisir manuellement la nouvelle date dans un tableau de suivi"


def unique_id(document: BpmnDocument, name: str) -> str:
    matches = [element.id for element in document.elements.values() if element.name == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one element named {name!r}, found {len(matches)}.")
    return matches[0]


def execute_change(source: Path, output: Path, request: str, **hints: object) -> None:
    document = BpmnDocument(source)
    plan = ChangePlanner(document, ProcessInspector(document)).plan(request, **hints)
    if plan["status"] != "ready_for_approval":
        raise RuntimeError(f"Setup plan was not executable: {plan}")
    result = BpmnPlanExecutor().execute(plan, output, approved=True)
    if result["status"] != "execution_succeeded":
        raise RuntimeError(f"Setup execution failed: {result}")


def main() -> None:
    for directory in (REFERENCE.parent, AS_IS.parent, AS_IS.parent.parent / "generated", AS_IS.parent.parent / "results"):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SOURCE, REFERENCE)

    with tempfile.TemporaryDirectory(prefix="scenario_002_") as temporary:
        temporary_dir = Path(temporary)
        renamed = temporary_dir / "renamed.bpmn"
        removed = temporary_dir / "removed.bpmn"

        reference = BpmnDocument(REFERENCE)
        execute_change(
            REFERENCE,
            renamed,
            "Préparer la dégradation de renommage.",
            operation="rename_element",
            target_element_id=unique_id(reference, ORIGINAL_RENAME),
            new_name=DEGRADED_RENAME,
        )

        renamed_document = BpmnDocument(renamed)
        execute_change(
            renamed,
            removed,
            "Préparer la dégradation par suppression.",
            operation="remove_element",
            target_element_id=unique_id(renamed_document, REMOVED_TASK),
        )

        removed_document = BpmnDocument(removed)
        execute_change(
            removed,
            AS_IS,
            "Préparer la dégradation par insertion.",
            operation="insert_task_after",
            target_element_id=unique_id(removed_document, INSERT_AFTER),
            new_name=ARTIFICIAL_TASK,
            new_bpmn_type="userTask",
            lane_name="Direction d'Approvisionnement",
        )

    validation = BasicValidator(BpmnDocument(AS_IS)).validate()
    if not validation["valid_for_agentic_editing"] or validation["error_count"]:
        raise RuntimeError(f"Generated AS-IS is not structurally valid: {validation}")

    if SOURCE.read_bytes() != REFERENCE.read_bytes():
        raise RuntimeError("Reference is not an unchanged byte-for-byte copy of the source.")

    print(f"Created {REFERENCE}")
    print(f"Created {AS_IS}")
    print("AS-IS validation: valid_for_agentic_editing=true, error_count=0")


if __name__ == "__main__":
    main()
