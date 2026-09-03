from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bpmn_agentic_engineer.llm.kaggle import KaggleQwenBridge

from .prompts import build_messages


class RecommendationKaggleBridge(KaggleQwenBridge):
    """Recommendation payload using the shared Kaggle/Qwen job pipeline."""

    def submit_context(
        self,
        *,
        run_id: str,
        context: dict[str, Any],
        job_root: str | Path,
        kernel_ref: str,
        accelerator: str = "NvidiaTeslaT4",
    ) -> dict[str, Any]:
        self._validate_kernel_ref(kernel_ref)
        self._ensure_cli()
        canonical = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        payload = {
            "schema_version": "1.0",
            "job_type": "recommend_optimizations",
            "result_filename": "recommendation_result.json",
            "run_id": run_id,
            "request_sha256": request_hash,
            "model_id": "Qwen/Qwen3-8B",
            "messages": build_messages(context),
        }
        return self._submit_payload(
            run_id=run_id,
            payload=payload,
            request_sha256=request_hash,
            job_root=job_root,
            kernel_ref=kernel_ref,
            accelerator=accelerator,
        )
