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
                json.dumps(result, ensure_ascii=False, indent=2) + "\\n",
                encoding="utf-8",
            )
            print(json.dumps({{"status": "ok", "output": str(OUTPUT)}}))


        if __name__ == "__main__":
            main()
        '''
    )
