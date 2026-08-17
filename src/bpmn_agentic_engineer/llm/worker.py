from __future__ import annotations

import json
from textwrap import dedent
from typing import Any


def render_qwen3_worker(payload: dict[str, Any]) -> str:
    embedded = json.dumps(payload, ensure_ascii=False)
    return dedent(
        f'''\
        from __future__ import annotations

        import json
        import os
        from pathlib import Path
        import re
        import subprocess
        import sys
        import unicodedata

        PAYLOAD = json.loads({embedded!r})
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
            cleaned = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", text.strip(), flags=re.I)
            start = cleaned.find("{{")
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
                    elif char == "\\\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{{":
                    depth += 1
                elif char == "}}":
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
                r"[^\\w]+",
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
            return {{}}


        def explicit_lane_from_request() -> tuple[str, str | None] | None:
            user_payload = user_request_payload()
            request = normalize_text(str(user_payload.get("request") or ""))
            catalogue = user_payload.get("bpmn_catalogue") or {{}}
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
            best = {{
                (lane_name, process_alias)
                for length, lane_name, process_alias in matches
                if length == longest
            }}
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
            if operation in {{
                "insert_task_before",
                "insert_task_after",
                "replace_linear_task_sequence",
            }}:
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
                json.dumps(result, ensure_ascii=False, indent=2) + "\\n",
                encoding="utf-8",
            )

            JOB_MANIFEST.write_text(
                json.dumps(
                    {{
                        "schema_version": PAYLOAD["schema_version"],
                        "run_id": PAYLOAD["run_id"],
                        "request_sha256": PAYLOAD["request_sha256"],
                        "model_id": MODEL_ID,
                        "status": "completed",
                    }},
                    ensure_ascii=False,
                    indent=2,
                ) + "\\n",
                encoding="utf-8",
            )

            print(
                json.dumps(
                    {{
                        "status": "ok",
                        "output": str(OUTPUT),
                        "manifest": str(JOB_MANIFEST),
                    }}
                )
            )


        if __name__ == "__main__":
            main()
        '''
    )
