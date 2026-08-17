from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

PAYLOAD = json.loads('{"schema_version": "1.0", "run_id": "run_81fb40111ce04bd0", "request_sha256": "86df431ff6d16df9f9fc787b4437c2d4dac5f14930d63eee1ff85152c1055d11", "model_id": "Qwen/Qwen3-8B", "messages": [{"role": "system", "content": "You interpret BPMN change requests. Return exactly one JSON object and nothing else.\\n\\nAllowed operations:\\n- insert_task_after\\n- insert_task_before\\n- rename_element\\n- remove_element\\n- replace_linear_task_sequence\\n- unsupported\\n\\nRequired schema:\\n{\\n  \\"schema_version\\": \\"1.1\\",\\n  \\"operation\\": \\"...\\",\\n  \\"target_query\\": \\"visible BPMN label or null\\",\\n  \\"source_queries\\": [\\"visible BPMN label\\", \\"...\\"] or [],\\n  \\"new_name\\": \\"visible new label or null\\",\\n  \\"new_bpmn_type\\": \\"task, userTask, manualTask, serviceTask, sendTask, receiveTask, scriptTask, businessRuleTask, or null\\",\\n  \\"lane_name\\": \\"visible actor/lane name or null\\",\\n  \\"process_alias\\": \\"process_N or null\\",\\n  \\"requires_clarification\\": true or false,\\n  \\"clarification_question\\": \\"one concise question or null\\",\\n  \\"confidence\\": 0.0 to 1.0\\n}\\n\\nOperation rules:\\n1. Use replace_linear_task_sequence only when the user explicitly asks to merge, consolidate,\\n   regroup, automate, or replace two or more named consecutive tasks with one task.\\n2. For replace_linear_task_sequence, put every existing task label in source_queries in the\\n   user\'s stated order, set target_query to null, and preserve the requested consolidated label.\\n3. Map \\"tâche de service\\" or \\"automatiser\\" to new_bpmn_type=\\"serviceTask\\" when explicit.\\n4. For all other operations, source_queries must be [] and new_bpmn_type should be null unless\\n   the request explicitly specifies the type of a newly inserted task.\\n5. For insert_task_after and insert_task_before, target_query is the existing anchor activity,\\n   while lane_name is the destination lane of the new task. The anchor may be in another lane.\\n6. When the user explicitly says \\"dans le couloir X\\" or names an actor lane, lane_name must be\\n   exactly X as written in the supplied BPMN catalogue. Never copy the anchor activity\'s lane.\\n7. For replace_linear_task_sequence, new_name is mandatory when the user gives the replacement\\n   label. Never put that replacement label in target_query. target_query must be null.\\n\\nExact cross-lane insertion example:\\n{\\n  \\"schema_version\\": \\"1.1\\",\\n  \\"operation\\": \\"insert_task_before\\",\\n  \\"target_query\\": \\"Choisir la simulation optimale\\",\\n  \\"source_queries\\": [],\\n  \\"new_name\\": \\"Effectuer une analyse financière\\",\\n  \\"new_bpmn_type\\": \\"userTask\\",\\n  \\"lane_name\\": \\"Direction Financière\\",\\n  \\"process_alias\\": \\"process_1\\",\\n  \\"requires_clarification\\": false,\\n  \\"clarification_question\\": null,\\n  \\"confidence\\": 0.95\\n}\\n\\nExact replace_linear_task_sequence example:\\n{\\n  \\"schema_version\\": \\"1.1\\",\\n  \\"operation\\": \\"replace_linear_task_sequence\\",\\n  \\"target_query\\": null,\\n  \\"source_queries\\": [\\"Task A\\", \\"Task B\\", \\"Task C\\"],\\n  \\"new_name\\": \\"Automated consolidated task\\",\\n  \\"new_bpmn_type\\": \\"serviceTask\\",\\n  \\"lane_name\\": \\"Actor lane\\",\\n  \\"process_alias\\": \\"process_1\\",\\n  \\"requires_clarification\\": false,\\n  \\"clarification_question\\": null,\\n  \\"confidence\\": 0.95\\n}\\n\\nSafety rules:\\n1. Never invent or return BPMN IDs, element IDs, process IDs, lane IDs, or sequence-flow IDs.\\n2. Use only process aliases from the supplied catalogue.\\n3. If several processes contain the same plausible target and the request does not distinguish\\n   them, set process_alias to null and requires_clarification to true.\\n4. Do not silently choose between duplicate activities.\\n5. Preserve the user\'s requested task name; do not expand it into a recommendation.\\n6. The deterministic local planner will ground labels, verify linearity, and perform XML edits.\\n7. Use unsupported when the requested control-flow edit is outside the allowed operations.\\n"}, {"role": "user", "content": "{\\"request\\":\\"Remplacez la séquence d\'activités « Exporter les résultats des simulations vers un fichier Excel », « Calculer manuellement la couverture de stock » et « Consolider les résultats de couverture de stock » par une seule tâche de service nommée « Génération automatique de la couverture de stock relatif à chaque simulation (Autonomie) » dans la lane « Direction d\'Approvisionnement ».\\",\\"bpmn_catalogue\\":{\\"process_count\\":1,\\"processes\\":[{\\"alias\\":\\"process_1\\",\\"participant_name\\":\\"Détermination des besoins d’approvisionnement\\",\\"flow_node_count\\":17,\\"lanes\\":[{\\"name\\":\\"Direction Financiére\\",\\"flow_node_count\\":0},{\\"name\\":\\"Direction d\'Approvisionnement\\",\\"flow_node_count\\":14},{\\"name\\":\\"Unité de Veille, Direction Commerciale, Direction Technique, Direction Générale et la CME\\",\\"flow_node_count\\":2},{\\"name\\":\\"unassigned\\",\\"flow_node_count\\":1}],\\"elements\\":[{\\"type\\":\\"callActivity\\",\\"name\\":\\"Approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"exclusiveGateway\\",\\"name\\":\\"Article nouvellement introduit ?\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Calculer manuellement la couverture de stock\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Choisir la simulation (solution) optimale\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Consolider les résultats de couverture de stock\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Effectuer plusieurs simulations de demandes d\'approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Envoyer le programme d\'approvisionnement par e-mail pour validation\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Exporter les résultats des simulations vers un fichier Excel\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"serviceTask\\",\\"name\\":\\"Génération des suggestions d\'achat d\'exploitation: hospitalier,Officinal,vaccin\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Générer le programme d\'approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Lancer le calcul des besoins (CBN) sur le SI\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Modifier et valider le programme d\'approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Modifier les critères de calcul d\'achat\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Renseigner le niveau de la consommation moyenne prévisionnelle\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réunion de validation\\",\\"lane\\":\\"Unité de Veille, Direction Commerciale, Direction Technique, Direction Générale et la CME\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Valider le programme d\'approvisionnement\\",\\"lane\\":\\"Unité de Veille, Direction Commerciale, Direction Technique, Direction Générale et la CME\\"}],\\"catalogue_truncated\\":false}],\\"rules\\":{\\"identifiers_hidden\\":true,\\"process_selection_uses_aliases\\":true}}}"}]}')
OUTPUT = Path("/kaggle/working/llm_interpretation.json")
RAW_OUTPUT = Path("/kaggle/working/llm_raw_output.txt")
JOB_MANIFEST = Path("/kaggle/working/llm_job_manifest.json")
MODEL_ID = "Qwen/Qwen3-8B"


def ensure_packages() -> None:
    # This worker uses PyTorch only. Prevent Transformers from loading
    # optional TensorFlow/Keras backends from the Kaggle image.
    os.environ["USE_TF"] = "0"
    os.environ["USE_FLAX"] = "0"
    os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

    # Kaggle currently ships a different Transformers stack.
    # Always replace it with one stable, reproducible Qwen3-compatible version.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "-y",
            "transformers",
            "tokenizers",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-cache-dir",
            "transformers==4.56.2",
            "accelerate>=1.0,<2",
            "bitsandbytes>=0.45,<0.49",
        ],
        check=True,
    )


def extract_json_object(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("The model output did not contain a JSON object.")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(cleaned[start:index + 1])
                if not isinstance(value, dict):
                    raise ValueError("The decoded JSON value is not an object.")
                return value
    raise ValueError("The model returned an incomplete JSON object.")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    punctuation_normalized = re.sub(
        r"[^\w]+",
        " ",
        without_accents.casefold(),
    )
    return " ".join(punctuation_normalized.split())


def user_request_payload() -> dict:
    for message in reversed(PAYLOAD.get("messages", [])):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    return {}


def explicit_lane_from_request() -> tuple[str, str | None] | None:
    user_payload = user_request_payload()
    request = normalize_text(str(user_payload.get("request") or ""))
    catalogue = user_payload.get("bpmn_catalogue") or {}
    if not request or not isinstance(catalogue, dict):
        return None

    matches: list[tuple[int, str, str | None]] = []
    for process in catalogue.get("processes", []):
        if not isinstance(process, dict):
            continue
        process_alias = process.get("alias")
        for lane in process.get("lanes", []):
            if not isinstance(lane, dict):
                continue
            lane_name = lane.get("name")
            if not isinstance(lane_name, str) or not lane_name.strip():
                continue
            normalized_lane = normalize_text(lane_name)
            if normalized_lane and normalized_lane in request:
                matches.append(
                    (len(normalized_lane), lane_name.strip(), process_alias)
                )

    if not matches:
        return None

    longest = max(length for length, _, _ in matches)
    best = {
        (lane_name, process_alias)
        for length, lane_name, process_alias in matches
        if length == longest
    }
    if len(best) != 1:
        return None
    return next(iter(best))


def normalize_result(result: dict) -> dict:
    normalized = dict(result)
    operation = normalized.get("operation")

    # Qwen occasionally puts the replacement label in target_query.
    if (
        operation == "replace_linear_task_sequence"
        and not normalized.get("new_name")
        and normalized.get("target_query")
    ):
        normalized["new_name"] = normalized["target_query"]
        normalized["target_query"] = None

    # The user's explicitly named lane is stronger than the model's guess.
    # Match only against exact lane labels present in the BPMN catalogue.
    if operation in {
        "insert_task_before",
        "insert_task_after",
        "replace_linear_task_sequence",
    }:
        explicit_lane = explicit_lane_from_request()
        if explicit_lane is not None:
            lane_name, process_alias = explicit_lane
            normalized["lane_name"] = lane_name
            if process_alias:
                normalized["process_alias"] = process_alias

    return normalized


def main() -> None:
    ensure_packages()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError("A Kaggle NVIDIA GPU accelerator is required.")

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        device_map="auto",
        dtype=torch.float16,
        quantization_config=quantization,
    )

    text = tokenizer.apply_chat_template(
        PAYLOAD["messages"],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    generated = model.generate(
        **model_inputs,
        max_new_tokens=384,
        do_sample=False,
        repetition_penalty=1.05,
    )
    new_tokens = generated[0][model_inputs.input_ids.shape[1]:]
    raw = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    RAW_OUTPUT.write_text(raw, encoding="utf-8")
    result = normalize_result(extract_json_object(raw))
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    JOB_MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": PAYLOAD["schema_version"],
                "run_id": PAYLOAD["run_id"],
                "request_sha256": PAYLOAD["request_sha256"],
                "model_id": MODEL_ID,
                "status": "completed",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(OUTPUT),
                "manifest": str(JOB_MANIFEST),
            }
        )
    )


if __name__ == "__main__":
    main()
