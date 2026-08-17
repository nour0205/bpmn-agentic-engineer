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
