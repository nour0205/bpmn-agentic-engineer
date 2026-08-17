from __future__ import annotations

import json

from bpmn_agentic_engineer.llm.worker import render_qwen3_worker


def _worker_namespace(request: str) -> dict:
    user_payload = {
        "request": request,
        "bpmn_catalogue": {
            "processes": [
                {
                    "alias": "process_1",
                    "lanes": [
                        {"name": "Direction d'Approvisionnement"},
                        {"name": "Direction Financiére"},
                    ],
                }
            ]
        },
    }
    payload = {
        "schema_version": "1.1",
        "run_id": "run_test",
        "request_sha256": "abc",
        "messages": [
            {"role": "system", "content": "test"},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    namespace = {"__name__": "generated_worker_test"}
    exec(compile(render_qwen3_worker(payload), "generated_worker.py", "exec"), namespace)
    return namespace


def test_explicit_lane_overrides_wrong_model_lane() -> None:
    namespace = _worker_namespace(
        "Ajoute l'activité « Effectuer une analyse financiére des simulations » "
        "avant « Choisir la simulation optimale », dans le couloir Direction Financiére."
    )
    result = namespace["normalize_result"](
        {
            "schema_version": "1.1",
            "operation": "insert_task_before",
            "target_query": "Choisir la simulation optimale",
            "source_queries": [],
            "new_name": "Effectuer une analyse financiére des simulations",
            "new_bpmn_type": "userTask",
            "lane_name": "Direction d'Approvisionnement",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 0.95,
        }
    )
    assert result["lane_name"] == "Direction Financiére"
    assert result["process_alias"] == "process_1"


def test_lane_is_not_overridden_when_request_names_no_catalogue_lane() -> None:
    namespace = _worker_namespace(
        "Ajoute l'activité « Vérifier le dossier » avant « Publier le dossier »."
    )
    result = namespace["normalize_result"](
        {
            "operation": "insert_task_before",
            "lane_name": "Direction d'Approvisionnement",
        }
    )
    assert result["lane_name"] == "Direction d'Approvisionnement"


def test_merge_replacement_name_is_recovered_from_target_query() -> None:
    namespace = _worker_namespace(
        "Fusionne les tâches en une tâche de service dans le couloir "
        "Direction d'Approvisionnement."
    )
    result = namespace["normalize_result"](
        {
            "operation": "replace_linear_task_sequence",
            "target_query": "Génération automatique de la couverture",
            "new_name": None,
            "lane_name": "Direction d'Approvisionnement",
        }
    )
    assert result["new_name"] == "Génération automatique de la couverture"
    assert result["target_query"] is None
