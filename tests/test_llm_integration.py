from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.llm import (
    CompactContextBuilder,
    enforce_generic_target_ambiguity,
    InterpretationValidator,
    KaggleQwenBridge,
    LlmInterpretation,
)
from bpmn_agentic_engineer.llm.worker import render_qwen3_worker
from bpmn_agentic_engineer.planning import ChangePlanner


FIXTURES = Path(__file__).parent / "fixtures"
CONTRACTS = Path(__file__).parents[1] / "data" / "bpmn" / "Gestion des contrats.bpmn"


def _catalogue(*names: str) -> dict:
    return {
        "processes": [
            {
                "alias": "process_1",
                "lanes": [{"name": "Direction d'Approvisionnement"}],
                "elements": [
                    {
                        "type": "userTask",
                        "name": name,
                        "lane": "Direction d'Approvisionnement",
                    }
                    for name in names
                ],
            }
        ]
    }


def _rename_result() -> dict:
    return {
        "schema_version": "1.1",
        "operation": "rename_element",
        "target_query": "Relancer le Fournisseur sur le portail et par téléphone",
        "new_name": "Traiter la relance",
        "lane_name": "Direction d'Approvisionnement",
        "process_alias": "process_1",
        "requires_clarification": False,
        "clarification_question": None,
        "confidence": 1.0,
        "source_queries": [],
        "new_bpmn_type": "userTask",
    }


def _contract_rename_result(target: str, lane: str | None) -> dict:
    return {
        "schema_version": "1.1",
        "operation": "rename_element",
        "target_query": target,
        "new_name": "Vérifier et valider le contrat",
        "lane_name": lane,
        "process_alias": "process_1",
        "requires_clarification": False,
        "clarification_question": None,
        "confidence": 1.0,
        "source_queries": [],
        "new_bpmn_type": None,
    }


def _plan_validated_contract_request(request: str, payload: dict) -> dict:
    document = BpmnDocument(CONTRACTS)
    validated = InterpretationValidator().validate(
        document,
        payload,
        request_text=request,
    )
    hints = validated["planner_hints"]
    return ChangePlanner(document, ProcessInspector(document)).plan(
        request,
        operation=hints["operation"],
        target_query=hints["target_query"],
        process_id=hints["process_id"],
        new_name=hints["new_name"],
        lane_name=hints["lane_name"],
    )


def test_duplicate_exact_name_requires_clarification_without_explicit_scope() -> None:
    plan = _plan_validated_contract_request(
        "Renommez l'activité « Revoir et valider le contrat » en "
        "« Vérifier et valider le contrat ».",
        _contract_rename_result(
            "Revoir et valider le contrat",
            "Responsable du Département Juridique",
        ),
    )
    assert plan["status"] == "requires_clarification"
    assert plan["requires_clarification"] is True
    assert {candidate["lane_name"] for candidate in plan["candidate_matches"]} == {
        "Direction d'Approvisionnement",
        "Responsable du Département Juridique",
    }


def test_duplicate_exact_name_with_explicit_lane_resolves_uniquely() -> None:
    plan = _plan_validated_contract_request(
        "Renommez l'activité « Revoir et valider le contrat » dans la lane "
        "« Responsable du Département Juridique » en « Vérifier et valider le contrat ».",
        _contract_rename_result(
            "Revoir et valider le contrat",
            "Direction d'Approvisionnement",
        ),
    )
    assert plan["status"] == "ready_for_approval"
    assert plan["selected_target"]["lane_name"] == "Responsable du Département Juridique"


def test_unique_exact_name_still_resolves_without_scope() -> None:
    plan = _plan_validated_contract_request(
        "Renommez l'activité « Imprimer et signer le contrat » en "
        "« Finaliser et signer le contrat ».",
        {
            **_contract_rename_result(
                "Imprimer et signer le contrat",
                "Responsable du Département Juridique",
            ),
            "new_name": "Finaliser et signer le contrat",
        },
    )
    assert plan["status"] == "ready_for_approval"
    assert plan["selected_target"]["name"] == "Imprimer et signer le contrat"


def test_generic_target_with_multiple_catalogue_matches_requires_clarification() -> None:
    result = enforce_generic_target_ambiguity(
        "Renommez l'activité liée à la relance en « Traiter la relance ».",
        _catalogue(
            "Relancer le Fournisseur sur le portail et par téléphone",
            "Générer les lettres de relance",
            "Valider la lettre de relance",
            "Transmettre la lettre de relance au Fournisseur via le portail et par mail",
        ),
        _rename_result(),
    )
    assert result["requires_clarification"] is True
    assert result["target_query"] is None
    assert result["clarification_question"]
    assert result["confidence"] <= 0.5


def test_exact_visible_target_does_not_force_clarification() -> None:
    result = enforce_generic_target_ambiguity(
        "Renommez l'activité « Relancer le Fournisseur sur le portail et par téléphone » "
        "en « Traiter la relance ».",
        _catalogue(
            "Relancer le Fournisseur sur le portail et par téléphone",
            "Générer les lettres de relance",
        ),
        _rename_result(),
    )
    assert result["requires_clarification"] is False
    assert result["target_query"] == "Relancer le Fournisseur sur le portail et par téléphone"


def test_generic_target_with_one_catalogue_match_does_not_force_clarification() -> None:
    result = enforce_generic_target_ambiguity(
        "Renommez la tâche concernant la facturation en « Traiter la facture ».",
        _catalogue("Contrôler la facturation", "Envoyer la commande"),
        _rename_result(),
    )
    assert result["requires_clarification"] is False


def test_rendered_worker_preserves_explicit_lane_normalization() -> None:
    user_payload = {
        "request": "Ajoutez une validation dans la lane Direction Générale.",
        "bpmn_catalogue": {
            "processes": [
                {
                    "alias": "process_1",
                    "lanes": [
                        {"name": "Direction Générale"},
                        {"name": "Direction d'Approvisionnement"},
                    ],
                }
            ]
        },
    }
    worker_source = render_qwen3_worker(
        {
            "messages": [
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
            ]
        }
    )
    namespace = {"__name__": "worker_test"}
    exec(compile(worker_source, "worker.py", "exec"), namespace)
    normalized = namespace["normalize_result"](
        {
            "operation": "insert_task_after",
            "lane_name": "Direction d'Approvisionnement",
            "process_alias": "process_1",
        }
    )
    assert normalized["lane_name"] == "Direction Générale"


def test_llm_schema_accepts_id_free_payload() -> None:
    interpretation = LlmInterpretation.from_dict(
        {
            "schema_version": "1.0",
            "operation": "insert_task_before",
            "target_query": "Rédiger le cahier des charges",
            "new_name": "Valider le dossier",
            "lane_name": "SPCM",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 0.93,
        },
        allowed_process_aliases={"process_1"},
    )
    assert interpretation.operation == "insert_task_before"
    assert interpretation.process_alias == "process_1"


def test_llm_schema_rejects_bpmn_ids() -> None:
    with pytest.raises(ValueError, match="not allowed to return BPMN identifiers"):
        LlmInterpretation.from_dict(
            {
                "operation": "rename_element",
                "target_query": "Task",
                "new_name": "New task",
                "process_alias": None,
                "requires_clarification": False,
                "clarification_question": None,
                "confidence": 0.8,
                "process_id": "Process_1",
            }
        )


def test_context_hides_real_identifiers() -> None:
    document = BpmnDocument(FIXTURES / "execution_process.bpmn")
    context = CompactContextBuilder(document).build()
    serialized = json.dumps(context.payload)
    assert "Process_1" not in serialized
    assert "Task_1" not in serialized
    assert context.process_alias_to_id == {"process_1": "Process_1"}
    assert context.payload["processes"][0]["alias"] == "process_1"


def test_interpretation_maps_alias_locally() -> None:
    document = BpmnDocument(FIXTURES / "execution_process.bpmn")
    result = InterpretationValidator().validate(
        document,
        {
            "schema_version": "1.0",
            "operation": "insert_task_before",
            "target_query": "Rédiger le cahier des charges",
            "new_name": "Valider le dossier",
            "lane_name": "SPCM",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 0.9,
        },
    )
    assert result["planner_hints"]["process_id"] == "Process_1"


def test_planner_accepts_explicit_llm_operation() -> None:
    document = BpmnDocument(FIXTURES / "execution_process.bpmn")
    plan = ChangePlanner(document, ProcessInspector(document)).plan(
        "Place une validation dans le flux.",
        operation="insert_task_before",
        target_query="Rédiger le cahier des charges",
        new_name="Valider le dossier",
        process_id="Process_1",
    )
    assert plan["status"] == "ready_for_approval"
    assert plan["request"]["operation"] == "insert_task_before"


def test_rendered_worker_is_valid_python(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        render_qwen3_worker(
            {
                "messages": [
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "Test"},
                ]
            }
        ),
        encoding="utf-8",
    )
    compile(worker.read_text(encoding="utf-8"), str(worker), "exec")


def test_kaggle_bridge_prepares_and_submits_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_runner(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="submitted", stderr="")

    monkeypatch.setattr("bpmn_agentic_engineer.llm.kaggle.shutil.which", lambda _: "kaggle")
    bridge = KaggleQwenBridge(command_runner=fake_runner)
    result = bridge.submit(
        run_id="run_test",
        file_path=FIXTURES / "execution_process.bpmn",
        request_text="Ajoute une validation avant la rédaction du cahier des charges.",
        job_root=tmp_path,
        kernel_ref="owner/bpmn-qwen3-interpreter",
    )

    kernel_dir = Path(result["kernel_dir"])
    assert (kernel_dir / "worker.py").exists()
    assert (kernel_dir / "kernel-metadata.json").exists()
    assert commands[0][:3] == ["kaggle", "kernels", "push"]
    assert "NvidiaTeslaT4" in commands[0]
