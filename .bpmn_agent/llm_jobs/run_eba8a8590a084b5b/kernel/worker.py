from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

PAYLOAD = json.loads('{"schema_version": "1.0", "run_id": "run_eba8a8590a084b5b", "request_sha256": "2b8553c21ca26881591e6f85671cc44c34633903a2e3fbcf490538b0185b6251", "model_id": "Qwen/Qwen3-8B", "messages": [{"role": "system", "content": "You interpret BPMN change requests. Return exactly one JSON object and nothing else.\\n\\nAllowed operations:\\n- insert_task_after\\n- insert_task_before\\n- rename_element\\n- remove_element\\n- replace_linear_task_sequence\\n- unsupported\\n\\nRequired schema:\\n{\\n  \\"schema_version\\": \\"1.1\\",\\n  \\"operation\\": \\"...\\",\\n  \\"target_query\\": \\"visible BPMN label or null\\",\\n  \\"source_queries\\": [\\"visible BPMN label\\", \\"...\\"] or [],\\n  \\"new_name\\": \\"visible new label or null\\",\\n  \\"new_bpmn_type\\": \\"task, userTask, manualTask, serviceTask, sendTask, receiveTask, scriptTask, businessRuleTask, or null\\",\\n  \\"lane_name\\": \\"visible actor/lane name or null\\",\\n  \\"process_alias\\": \\"process_N or null\\",\\n  \\"requires_clarification\\": true or false,\\n  \\"clarification_question\\": \\"one concise question or null\\",\\n  \\"confidence\\": 0.0 to 1.0\\n}\\n\\nOperation rules:\\n1. Use replace_linear_task_sequence only when the user explicitly asks to merge, consolidate,\\n   regroup, automate, or replace two or more named consecutive tasks with one task.\\n2. For replace_linear_task_sequence, put every existing task label in source_queries in the\\n   user\'s stated order, set target_query to null, and preserve the requested consolidated label.\\n3. Map \\"tâche de service\\" or \\"automatiser\\" to new_bpmn_type=\\"serviceTask\\" when explicit.\\n4. For all other operations, source_queries must be [] and new_bpmn_type should be null unless\\n   the request explicitly specifies the type of a newly inserted task.\\n5. For insert_task_after and insert_task_before, target_query is the existing anchor activity,\\n   while lane_name is the destination lane of the new task. The anchor may be in another lane.\\n\\nSafety rules:\\n1. Never invent or return BPMN IDs, element IDs, process IDs, lane IDs, or sequence-flow IDs.\\n2. Use only process aliases from the supplied catalogue.\\n3. If several processes contain the same plausible target and the request does not distinguish\\n   them, set process_alias to null and requires_clarification to true.\\n4. Do not silently choose between duplicate activities.\\n5. Preserve the user\'s requested task name; do not expand it into a recommendation.\\n6. The deterministic local planner will ground labels, verify linearity, and perform XML edits.\\n7. Use unsupported when the requested control-flow edit is outside the allowed operations.\\n"}, {"role": "user", "content": "{\\"request\\":\\"Fusionne les activités « Exporter les résultats des simulations vers un fichier Excel », « Calculer manuellement la couverture de stock » et « Consolider les résultats de couverture de stock » en une seule tâche de service « Génération automatique de la couverture de stock relatif à chaque simulation (Autonomie) », dans le couloir Direction d\'Approvisionnement.\\",\\"bpmn_catalogue\\":{\\"process_count\\":1,\\"processes\\":[{\\"alias\\":\\"process_1\\",\\"participant_name\\":\\"Détermination des besoins d’approvisionnement\\",\\"flow_node_count\\":17,\\"lanes\\":[{\\"name\\":\\"Direction d\'Approvisionnement\\",\\"flow_node_count\\":14},{\\"name\\":\\"Unité de Veille, Direction Commerciale, Direction Technique, Direction Générale et la CME\\",\\"flow_node_count\\":2},{\\"name\\":\\"unassigned\\",\\"flow_node_count\\":1}],\\"elements\\":[{\\"type\\":\\"callActivity\\",\\"name\\":\\"Approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"exclusiveGateway\\",\\"name\\":\\"Article nouvellement introduit ?\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Calculer manuellement la couverture de stock\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Choisir la simulation (solution) optimale\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Consolider les résultats de couverture de stock\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Effectuer plusieurs simulations de demandes d\'approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Envoyer le programme d\'approvisionnement par e-mail pour validation\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Exporter les résultats des simulations vers un fichier Excel\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"serviceTask\\",\\"name\\":\\"Génération des suggestions d\'achat d\'exploitation: hospitalier,Officinal,vaccin\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Générer le programme d\'approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Lancer le calcul des besoins (CBN) sur le SI\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Modifier et valider le programme d\'approvisionnement\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Modifier les critères de calcul d\'achat\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Renseigner le niveau de la consommation moyenne prévisionnelle\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réunion de validation\\",\\"lane\\":\\"Unité de Veille, Direction Commerciale, Direction Technique, Direction Générale et la CME\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Valider le programme d\'approvisionnement\\",\\"lane\\":\\"Unité de Veille, Direction Commerciale, Direction Technique, Direction Générale et la CME\\"}],\\"catalogue_truncated\\":false}],\\"rules\\":{\\"identifiers_hidden\\":true,\\"process_selection_uses_aliases\\":true}}}"}]}')
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
    result = extract_json_object(raw)
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
