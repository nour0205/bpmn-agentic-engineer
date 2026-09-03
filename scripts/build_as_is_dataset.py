"""Deterministically rebuild the AS-IS BPMN evaluation dataset from CIBLE files."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


ROOT = Path(__file__).parents[1]
CIBLE_DIR = ROOT / "data" / "bpmn" / "cible"
AS_IS_DIR = ROOT / "data" / "bpmn" / "as_is"
MANIFEST_PATH = ROOT / "data" / "bpmn" / "dataset_manifest.json"
SUPPORTED_OPERATIONS = {
    "insert_task_before",
    "insert_task_after",
    "rename_element",
    "remove_element",
    "replace_linear_task_sequence",
}


CASES = [
    {
        "case_id": "process_1",
        "filename": "Approvisionnement Gré à gré&Mise en place.bpmn",
        "process_name": "Approvisionnement par gré à gré / Mise en place",
        "process_id": "Id_e76115c1-faf6-4309-bf66-6d9c913e318a",
        "recipes": [
            {"category": "missing_control", "kind": "remove", "target": "Id_b9845a20-7617-4a14-8f63-dfea3620fa0a", "description": "L'archivage du procès-verbal dans la GED est absent.", "expected_operation": "insert_task_after", "restore_anchor": "Id_6b591ccc-7c5e-4ae3-a5bb-989c70b8fa7d", "restore_name": "Uploader le PV sur le système de gestion électronique des documents (GED)", "lane": "Secrétariat de la Commission d’Achats des Médicaments (CAM)"},
            {"category": "redundant_activity", "kind": "insert_task_before", "target": "Id_dd585253-78ef-48c4-b58d-e2674330d660", "name": "Envoyer manuellement le dossier contractuel par e-mail", "lane": "Direction d'Approvisionnement", "description": "Un envoi manuel redondant précède la gestion contractuelle.", "expected_operation": "remove_element"},
            {"category": "legacy_label", "kind": "rename", "target": "Id_d4366c16-f3a5-48b8-b8db-78ab4f7ba446", "name": "Saisir manuellement la fiche article dans l'ancien écran SI", "description": "La fiche article porte un libellé technique hérité.", "expected_operation": "rename_element"},
        ],
    },
    {
        "case_id": "process_2",
        "filename": "Approvisionnement par Appel d'offres.bpmn",
        "process_name": "Préparation et traitement des commandes d’achat - Par Appel d'offres",
        "process_id": "Id_1a378fa6-28f6-4313-b53f-35ddd52a25a7",
        "recipes": [
            {"category": "missing_control", "kind": "remove", "target": "Id_bd964e40-ca81-4d88-8a1e-1f4f59c96d6b", "description": "L'archivage contrôlé du cahier des charges dans la GED est absent.", "expected_operation": "insert_task_after", "restore_anchor": "Id_d985cf4d-0f92-42db-8f44-f88d8fb6b61e", "restore_name": "Uploader le CDC sur le système de gestion électronique des documents (GED)", "lane": "SPCM"},
            {"category": "redundant_activity", "kind": "insert_task_before", "target": "Id_1b6a9ad8-fe94-44a6-ae3d-da5152d4469d", "name": "Envoyer manuellement le tableau comparatif aux responsables par e-mail", "lane": "Direction d'Approvisionnement", "description": "Une diffusion manuelle redondante précède la sélection du Fournisseur.", "expected_operation": "remove_element"},
            {"category": "legacy_label", "kind": "rename", "target": "Id_264ff46e-db65-4fff-a106-8c0061e26952", "name": "Importer manuellement le fichier financier dans l'ancien écran SI", "description": "L'intégration financière conserve un libellé d'ancien mode opératoire.", "expected_operation": "rename_element"},
        ],
    },
    {
        "case_id": "process_3",
        "filename": "Détermination des besoins d'approvisionnement.bpmn",
        "process_name": "Détermination des besoins d’approvisionnement",
        "process_id": "Id_e6326128-4d51-4eee-b38c-c74471effa51",
        "recipes": [
            {"category": "manual_sequence", "kind": "manualize", "target": "Id_c785a05d-e52d-4a18-ad55-5389b2af29c8", "first_name": "Exporter les résultats de simulation vers Excel", "additional": ["Calculer manuellement la couverture de stock", "Consolider les couvertures calculées"], "lane": "Direction d'Approvisionnement", "description": "Le calcul automatique de couverture devient une chaîne manuelle Excel.", "expected_operation": "replace_linear_task_sequence"},
            {"category": "missing_control", "kind": "remove", "target": "Id_8070c07c-058f-4955-9be0-542e8757784e", "description": "L'analyse financière des simulations est omise avant le choix optimal.", "expected_operation": "insert_task_before", "restore_anchor": "Id_4a2a1c70-f704-4713-9b0b-717e06ba4b91", "restore_name": "Effectuer une analyse financiére des simulations", "lane": "Direction Financiére"},
            {"category": "redundant_activity", "kind": "insert_task_after", "target": "Id_87b782da-2f76-463a-8d76-7b885d5f564e", "name": "Copier manuellement les simulations dans un fichier de suivi", "lane": "Direction d'Approvisionnement", "description": "Une copie manuelle redondante est ajoutée après les simulations.", "expected_operation": "remove_element"},
        ],
    },
    {
        "case_id": "process_4",
        "filename": "Gestion des contrats.bpmn",
        "process_name": "Gestion des contrats",
        "process_id": "Id_c58e5e64-12ab-407d-9b7f-f539747eefc6",
        "recipes": [
            {"category": "manual_sequence", "kind": "manualize", "target": "Id_3d54e3ee-19ee-4408-b045-6e5c8bbbd139", "first_name": "Se connecter manuellement au portail Fournisseur", "additional": ["Télécharger et classer le contrat signé dans le SI"], "lane": "Direction d'Approvisionnement", "description": "La récupération automatique du contrat signé devient manuelle.", "expected_operation": "replace_linear_task_sequence"},
            {"category": "missing_control", "kind": "remove", "target": "Id_efd322c2-715d-465d-9f7e-079fba3bff87", "description": "La revue juridique du contrat est omise après la revue Approvisionnement.", "expected_operation": "insert_task_after", "restore_anchor": "Id_f41ade0b-5337-4e06-8a0f-4ef411081ce2", "restore_name": "Revoir et valider le contrat", "lane": "Responsable du Département Juridique"},
            {"category": "legacy_label", "kind": "rename", "target": "Id_47167652-5b08-4cb4-99fb-81eb6f5db218", "name": "Récupérer le fichier draft envoyé par le Fournisseur", "description": "La réception du projet de contrat utilise un ancien libellé orienté fichier.", "expected_operation": "rename_element"},
        ],
    },
    {
        "case_id": "process_5",
        "filename": "Lancement des commandes.bpmn",
        "process_name": "Lancement des commandes",
        "process_id": "Id_fb535085-ad3b-407b-a577-bfcaccb8c23e",
        "recipes": [
            {"category": "manual_sequence", "kind": "manualize", "target": "Id_c239fba4-5e23-4627-9c1b-a3b2b10049e5", "first_name": "Exporter les commandes dans un tableur", "additional": ["Construire manuellement le planning de livraison"], "lane": "Direction d'Approvisionnement", "description": "La suggestion automatique du planning devient une préparation manuelle.", "expected_operation": "replace_linear_task_sequence"},
            {"category": "redundant_activity", "kind": "insert_task_before", "target": "Id_97cad88e-1f91-4e15-a224-120d865e608b", "name": "Transmettre manuellement le dossier d'importation au Transit", "lane": "Direction d'Approvisionnement", "description": "Une transmission manuelle redondante précède le sous-processus Transit.", "expected_operation": "remove_element"},
            {"category": "legacy_label", "kind": "rename", "target": "Id_41cdc504-6b4f-4b82-8847-31ea80ea0c94", "name": "Envoyer les documents de commande en pièces jointes par e-mail", "description": "L'envoi de commande conserve un libellé centré sur les pièces jointes.", "expected_operation": "rename_element"},
        ],
    },
    {
        "case_id": "process_6",
        "filename": "Suivi des commandes.bpmn",
        "process_name": "Suivi des commandes",
        "process_id": "Id_14e4a3e9-61cb-46d3-8ab0-3058189f16da",
        "recipes": [
            {"category": "manual_sequence", "kind": "manualize", "target": "Id_cb31e508-73e6-4f40-a87d-63a9772d98fc", "first_name": "Exporter la liste des commandes en cours", "additional": ["Consolider manuellement le reporting des commandes"], "lane": "Direction d'Approvisionnement", "description": "Le reporting automatique devient une consolidation manuelle.", "expected_operation": "replace_linear_task_sequence"},
            {"category": "missing_control", "kind": "remove", "target": "Id_7707912d-3d8b-4b43-b170-13f088fbbe93", "description": "La validation Direction Générale de la lettre de relance est absente.", "expected_operation": "insert_task_after", "restore_anchor": "Id_a761d73c-82aa-42cf-bd99-bd23b1573a10", "restore_name": "Valider la lettre de relance", "lane": "Direction Générale"},
            {"category": "redundant_activity", "kind": "insert_task_after", "target": "Id_98828c6c-2aaa-4017-8d07-60d1365b92c5", "name": "Consigner manuellement la relance dans un fichier partagé", "lane": "Direction d'Approvisionnement", "description": "Une consignation manuelle redondante suit la relance Fournisseur.", "expected_operation": "remove_element"},
        ],
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _manualize(path: Path, element_id: str, first_name: str) -> None:
    tree = ET.parse(path)
    element = next(node for node in tree.getroot().iter() if node.get("id") == element_id)
    namespace = element.tag.split("}", 1)[0] + "}"
    element.tag = namespace + "userTask"
    element.set("name", first_name)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _deterministic_uuid(case_id: str, step: int):
    counter = 0

    def create() -> uuid.UUID:
        nonlocal counter
        counter += 1
        return uuid.uuid5(uuid.NAMESPACE_URL, f"bpmn-dataset:{case_id}:{step}:{counter}")

    return create


def _execute(current: Path, case_id: str, step: int, **hints) -> tuple[Path, list[str]]:
    before = BpmnDocument(current)
    planner = ChangePlanner(before, ProcessInspector(before))
    plan = planner.plan("Dégradation déterministe du jeu de données.", **hints)
    if plan["status"] != "ready_for_approval":
        raise RuntimeError(f"Recipe {case_id}/{step} did not plan: {plan}")
    output = current.with_name(f"stage_{step:02d}.bpmn")
    with patch(
        "bpmn_agentic_engineer.execution.executor.uuid.uuid4",
        side_effect=_deterministic_uuid(case_id, step),
    ):
        result = BpmnPlanExecutor().execute(plan, output, approved=True)
    if result["status"] != "execution_succeeded":
        raise RuntimeError(f"Recipe {case_id}/{step} failed: {result}")
    after = BpmnDocument(output)
    added = sorted(set(after.elements) - set(before.elements))
    current.unlink()
    return output, added


def _semantic_signature(document: BpmnDocument) -> dict:
    return {
        "elements": {key: value.to_dict() for key, value in sorted(document.elements.items())},
        "flows": {key: value.to_dict() for key, value in sorted(document.sequence_flows.items())},
        "lanes": {key: value for key, value in sorted(document.lanes.items())},
    }


def _cross_process_flows(document: BpmnDocument) -> list[str]:
    failures = []
    for flow in document.sequence_flows.values():
        source = document.elements.get(flow.source_ref)
        target = document.elements.get(flow.target_ref)
        if source and target and (source.process_id != target.process_id or source.process_id != flow.process_id):
            failures.append(flow.id)
    return failures


def build_dataset() -> dict:
    AS_IS_DIR.mkdir(parents=True, exist_ok=True)
    before_hashes = {path.name: sha256(path) for path in CIBLE_DIR.glob("*.bpmn")}
    manifest = {"schema_version": "1.0", "ground_truth_only": True, "cases": []}
    with tempfile.TemporaryDirectory(prefix="bpmn_dataset_") as temporary:
        temporary_root = Path(temporary)
        for case in CASES:
            cible = CIBLE_DIR / case["filename"]
            as_is = AS_IS_DIR / case["filename"]
            work_dir = temporary_root / case["case_id"]
            work_dir.mkdir()
            current = work_dir / "stage_00.bpmn"
            shutil.copy2(cible, current)
            issues = []
            step = 0
            for issue_index, recipe in enumerate(case["recipes"], 1):
                as_is_elements: list[str] = []
                if recipe["kind"] == "manualize":
                    _manualize(current, recipe["target"], recipe["first_name"])
                    as_is_elements.append(recipe["target"])
                    anchor = recipe["target"]
                    for name in recipe["additional"]:
                        step += 1
                        current, added = _execute(
                            current, case["case_id"], step,
                            operation="insert_task_after", target_element_id=anchor,
                            process_id=case["process_id"], new_name=name,
                            new_bpmn_type="userTask", lane_name=recipe["lane"],
                        )
                        anchor = added[0]
                        as_is_elements.extend(added)
                elif recipe["kind"] == "remove":
                    step += 1
                    current, _ = _execute(
                        current, case["case_id"], step,
                        operation="remove_element", target_element_id=recipe["target"],
                        process_id=case["process_id"],
                    )
                elif recipe["kind"] == "rename":
                    step += 1
                    current, _ = _execute(
                        current, case["case_id"], step,
                        operation="rename_element", target_element_id=recipe["target"],
                        process_id=case["process_id"], new_name=recipe["name"],
                    )
                    as_is_elements.append(recipe["target"])
                else:
                    step += 1
                    current, added = _execute(
                        current, case["case_id"], step,
                        operation=recipe["kind"], target_element_id=recipe["target"],
                        process_id=case["process_id"], new_name=recipe["name"],
                        new_bpmn_type="userTask", lane_name=recipe["lane"],
                    )
                    as_is_elements.extend(added)
                issue = {
                    "id": f"issue_{issue_index:02d}",
                    "category": recipe["category"],
                    "description": recipe["description"],
                    "as_is_elements": as_is_elements,
                    "cible_element": recipe.get("target"),
                    "expected_operation": recipe["expected_operation"],
                    "executable_by_current_engine": recipe["expected_operation"] in SUPPORTED_OPERATIONS,
                }
                for key in ("restore_anchor", "restore_name", "lane"):
                    if key in recipe:
                        issue[key] = recipe[key]
                issues.append(issue)
            shutil.copy2(current, as_is)
            cible_doc, as_is_doc = BpmnDocument(cible), BpmnDocument(as_is)
            cible_validation = BasicValidator(cible_doc).validate()
            as_is_validation = BasicValidator(as_is_doc).validate()
            if cible_validation["error_count"] or as_is_validation["error_count"]:
                raise RuntimeError(f"Invalid pair: {case['case_id']}")
            if _cross_process_flows(as_is_doc):
                raise RuntimeError(f"Cross-process flow in {case['case_id']}")
            if _semantic_signature(cible_doc) == _semantic_signature(as_is_doc):
                raise RuntimeError(f"AS-IS equals CIBLE: {case['case_id']}")
            manifest["cases"].append({
                "case_id": case["case_id"],
                "as_is": as_is.relative_to(ROOT).as_posix(),
                "cible": cible.relative_to(ROOT).as_posix(),
                "process_name": case["process_name"],
                "process_id": case["process_id"],
                "cible_sha256": before_hashes[cible.name],
                "as_is_sha256": sha256(as_is),
                "introduced_issues": issues,
                "intentional_differences": len(issues),
                "unexplained_differences": 0,
                "as_is_structural_errors": as_is_validation["error_count"],
                "cible_structural_errors": cible_validation["error_count"],
            })
    after_hashes = {path.name: sha256(path) for path in CIBLE_DIR.glob("*.bpmn")}
    if before_hashes != after_hashes:
        raise RuntimeError("A CIBLE checksum changed during dataset generation.")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    built = build_dataset()
    print(json.dumps({"cases": len(built["cases"]), "manifest": str(MANIFEST_PATH)}, indent=2))
