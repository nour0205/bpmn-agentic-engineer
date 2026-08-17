from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

PAYLOAD = json.loads('{"schema_version": "1.0", "run_id": "run_2e5518729ddb4115", "request_sha256": "8efd329b2307c09c9aa42c0b9535c24c839423c6cb77c16833d3daf39b183408", "model_id": "Qwen/Qwen3-8B", "messages": [{"role": "system", "content": "You interpret BPMN change requests. Return exactly one JSON object and nothing else.\\n\\nAllowed operations:\\n- insert_task_after\\n- insert_task_before\\n- rename_element\\n- remove_element\\n- unsupported\\n\\nRequired schema:\\n{\\n  \\"schema_version\\": \\"1.0\\",\\n  \\"operation\\": \\"...\\",\\n  \\"target_query\\": \\"visible BPMN label or null\\",\\n  \\"new_name\\": \\"visible new label or null\\",\\n  \\"lane_name\\": \\"visible actor/lane name or null\\",\\n  \\"process_alias\\": \\"process_N or null\\",\\n  \\"requires_clarification\\": true or false,\\n  \\"clarification_question\\": \\"one concise question or null\\",\\n  \\"confidence\\": 0.0 to 1.0\\n}\\n\\nSafety rules:\\n1. Never invent or return BPMN IDs, element IDs, process IDs, lane IDs, or sequence-flow IDs.\\n2. Use only process aliases from the supplied catalogue.\\n3. If several processes contain the same plausible target and the request does not distinguish\\n   them, set process_alias to null and requires_clarification to true.\\n4. Do not silently choose between duplicate activities.\\n5. Preserve the user\'s requested task name; do not expand it into a recommendation.\\n6. The deterministic local planner will ground labels and perform all XML operations.\\n7. Use unsupported when the requested control-flow edit is outside the four allowed operations.\\n"}, {"role": "user", "content": "{\\"request\\":\\"Ajoute une validation du dossier par le SPCM avant la rédaction du cahier des charges\\",\\"bpmn_catalogue\\":{\\"process_count\\":3,\\"processes\\":[{\\"alias\\":\\"process_1\\",\\"participant_name\\":\\"Préparation et traitement des commandes d’achat - Par Appel d\'offres\\",\\"flow_node_count\\":20,\\"lanes\\":[{\\"name\\":\\"Commission d\'ouverture de plis\\",\\"flow_node_count\\":4},{\\"name\\":\\"Direction Technique\\",\\"flow_node_count\\":1},{\\"name\\":\\"Direction d\'Approvisionnement\\",\\"flow_node_count\\":4},{\\"name\\":\\"SPCM\\",\\"flow_node_count\\":6},{\\"name\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\",\\"flow_node_count\\":4},{\\"name\\":\\"Unité Base de Données\\",\\"flow_node_count\\":1}],\\"elements\\":[{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"A la réception des réponses à l’appel d’offre au niveau de TUNEPS\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Procéder à l\'ouverture des plis\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger, imprimer et signer le PV d\'ouverture des plis\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Uploader le PV sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Renseigner les réponses techniques au niveau du SI par un modèle d\'import\\",\\"lane\\":\\"Direction Technique\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Générer un tableau comparatif des offres directement au niveau du SI\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Renseigner les réponses financières au niveau du SI par modèle d\'import\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Sélection du Fournisseur et lancement des commandes\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Transférer les plis des réponses à la Direction Technique\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Créer un dossier d\'appel d\'offres et renseigner son numéro\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Détermination des besoins d\'approvisionnement\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Lancement de l\'appel d\'offres sur TUNEPS par la CME\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger le cahier des charges en concertation avec les parties prenantes concernées\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Répondre aux demandes d\'éclaircissements des soumissionnaires\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Uploader le CDC sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réception d\'une demande d\'AMM auprès des Fournisseurs\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger et imprimer un PV contenant la décision de mise sur le marché\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réunion de la CAM, et attribution de l\'AMM aux Fournisseurs\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Uploader le PV sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Créer les fiches Fournisseurs sur le SI avec le statut \'\'Prospect\'\'\\",\\"lane\\":\\"Unité Base de Données\\"}],\\"catalogue_truncated\\":false},{\\"alias\\":\\"process_2\\",\\"participant_name\\":\\"Préparation et traitement des commandes d’achat - Par Appel d\'offres\\",\\"flow_node_count\\":33,\\"lanes\\":[{\\"name\\":\\"Commission d\'ouverture de plis\\",\\"flow_node_count\\":4},{\\"name\\":\\"Commission de dépouillement des offres\\",\\"flow_node_count\\":3},{\\"name\\":\\"Direction Technique\\",\\"flow_node_count\\":1},{\\"name\\":\\"Direction d\'Approvisionnement\\",\\"flow_node_count\\":12},{\\"name\\":\\"SPCM\\",\\"flow_node_count\\":6},{\\"name\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\",\\"flow_node_count\\":4},{\\"name\\":\\"Unité Base de Données\\",\\"flow_node_count\\":3}],\\"elements\\":[{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"A la réception des réponses à l’appel d’offre au niveau de TUNEPS\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Procéder à l\'ouverture des plis\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger, imprimer et signer le PV d\'ouverture des plis\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Uploader le PV sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"Commission d\'ouverture de plis\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger, signer et imprimer le PV de dépouillement\\",\\"lane\\":\\"Commission de dépouillement des offres\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réunion de la commission de dépouillement avec la CME\\",\\"lane\\":\\"Commission de dépouillement des offres\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Uploader le PV sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"Commission de dépouillement des offres\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Renseigner les réponses techniques au niveau du SI par un modèle d\'import\\",\\"lane\\":\\"Direction Technique\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"A la réception des réponses de la CAM ou de la CSM\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Gestion des contrats\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Gestion des réceptions\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Générer un tableau comparatif des offres directement au niveau du SI\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Lancement des commandes\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Préparer la proposition d’attribution du marché et la transmettre à la CME\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Présentation de la proposition par la CME à la CAM ou à la CSM\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Renseigner les réponses financières au niveau du SI par modèle d\'import\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Suivi des commandes\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Sélectionner les Fournisseurs retenus sur le SI\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Transférer les plis des réponses à la Direction Technique\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Transmission des classements financiers et techniques à la CME\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Créer un dossier d\'appel d\'offres et renseigner son numéro\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Détermination des besoins d\'approvisionnement\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Lancement de l\'appel d\'offres sur TUNEPS par la CME\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger le cahier des charges en concertation avec les parties prenantes concernées\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Répondre aux demandes d\'éclaircissements des soumissionnaires\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Uploader le CDC sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"SPCM\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réception d\'une demande d\'AMM auprès des Fournisseurs\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger et imprimer un PV contenant la décision de mise sur le marché\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réunion de la CAM, et attribution de l\'AMM aux Fournisseurs\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"task\\",\\"name\\":\\"Uploader le PV sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"Secrétariat de la Commission d’Achats des Médicaments (CAM)\\"},{\\"type\\":\\"serviceTask\\",\\"name\\":\\"Création automatique du/des Fournisseurs retenu(s) sur le Portail Fournisseur\\",\\"lane\\":\\"Unité Base de Données\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Créer les fiches Fournisseurs sur le SI avec le statut \'\'Prospect\'\'\\",\\"lane\\":\\"Unité Base de Données\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Mettre à jour le statut du / des Fournisseur(s)\\",\\"lane\\":\\"Unité Base de Données\\"}],\\"catalogue_truncated\\":false},{\\"alias\\":\\"process_3\\",\\"participant_name\\":\\"Préparation et traitement des commandes d’achat - Par Appel d\'offres\\",\\"flow_node_count\\":14,\\"lanes\\":[{\\"name\\":\\"Commission de dépouillement des offres\\",\\"flow_node_count\\":3},{\\"name\\":\\"Direction d\'Approvisionnement\\",\\"flow_node_count\\":9},{\\"name\\":\\"Unité Base de Données\\",\\"flow_node_count\\":2}],\\"elements\\":[{\\"type\\":\\"task\\",\\"name\\":\\"Rédiger, signer et imprimer le PV de dépouillement\\",\\"lane\\":\\"Commission de dépouillement des offres\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Réunion de la commission de dépouillement avec la CME\\",\\"lane\\":\\"Commission de dépouillement des offres\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Uploader le PV sur le système de gestion électronique des documents (GED)\\",\\"lane\\":\\"Commission de dépouillement des offres\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"A la réception des réponses de la CAM ou de la CSM\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Gestion des contrats\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Gestion des réceptions\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Lancement des commandes\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Préparer la proposition d’attribution du marché et la transmettre à la CME\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Présentation de la proposition par la CME à la CAM ou à la CSM\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"callActivity\\",\\"name\\":\\"Suivi des commandes\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Sélectionner les Fournisseurs retenus sur le SI\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"intermediateThrowEvent\\",\\"name\\":\\"Transmission des classements financiers et techniques à la CME\\",\\"lane\\":\\"Direction d\'Approvisionnement\\"},{\\"type\\":\\"serviceTask\\",\\"name\\":\\"Création automatique du/des Fournisseurs retenu(s) sur le Portail Fournisseur\\",\\"lane\\":\\"Unité Base de Données\\"},{\\"type\\":\\"userTask\\",\\"name\\":\\"Mettre à jour le statut du / des Fournisseur(s)\\",\\"lane\\":\\"Unité Base de Données\\"}],\\"catalogue_truncated\\":false}],\\"rules\\":{\\"identifiers_hidden\\":true,\\"process_selection_uses_aliases\\":true}}}"}]}')
OUTPUT = Path("/kaggle/working/llm_interpretation.json")
RAW_OUTPUT = Path("/kaggle/working/llm_raw_output.txt")
JOB_MANIFEST = Path("/kaggle/working/llm_job_manifest.json")
MODEL_ID = "Qwen/Qwen3-8B"


def ensure_packages() -> None:
    required = ["transformers", "accelerate", "bitsandbytes"]
    missing = []
    for package in required:
        try:
            __import__(package)
        except Exception:
            missing.append(package)
    if missing:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "transformers>=4.51,<5",
                "accelerate>=1.0",
                "bitsandbytes>=0.45",
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
        do_sample=True,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
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
    print(json.dumps({"status": "ok", "output": str(OUTPUT)}))


if __name__ == "__main__":
    main()
