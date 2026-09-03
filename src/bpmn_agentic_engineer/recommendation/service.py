from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bpmn_agentic_engineer.analysis import BpmnAnalyzer
from bpmn_agentic_engineer.bpmn import BpmnDocument

from .context import RecommendationContextBuilder
from .kaggle import RecommendationKaggleBridge
from .models import RecommendationResult
from .ranking import rank_recommendations
from .validator import RecommendationValidator


class BpmnRecommendationService:
    """Read-only evidence → Qwen → locally validated recommendation pipeline."""

    def __init__(
        self,
        state_dir: str | Path = ".bpmn_agent",
        *,
        bridge: Any | None = None,
        kernel_ref: str = "nourkouider05/bpmn-qwen3-interpreter",
        poll_interval: float = 10.0,
        timeout: float = 3600.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        progress_handler: Callable[[str], None] | None = None,
    ):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.bridge = bridge or RecommendationKaggleBridge()
        self.kernel_ref = kernel_ref
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.sleep = sleep
        self.clock = clock
        self.progress = progress_handler or (lambda _message: None)

    def recommend(self, bpmn_path: str | Path, goal: str | None = None) -> RecommendationResult:
        document = BpmnDocument(bpmn_path)
        analysis = BpmnAnalyzer().analyze(document.path)
        if not analysis.validation_summary["valid_for_agentic_editing"]:
            raise ValueError("The AS-IS BPMN has blocking structural validation errors.")
        context = RecommendationContextBuilder().build(document, analysis, goal=goal)
        self.progress("Deterministic BPMN evidence prepared.")
        payload = self._generate(context)
        recommendations, rejected = RecommendationValidator().validate(document, analysis, payload)
        recommendations = rank_recommendations(recommendations)
        return RecommendationResult(
            source_file=str(document.path),
            process_name=analysis.process_name,
            goal=" ".join(goal.split()) if goal else None,
            recommendations=tuple(recommendations),
            rejected_recommendations=len(rejected),
        )

    def _generate(self, context: dict[str, Any]) -> dict[str, Any]:
        if hasattr(self.bridge, "generate"):
            result = self.bridge.generate(context)
            if not isinstance(result, dict):
                raise ValueError("Qwen recommendation output must be one JSON object.")
            return result
        run_id = f"recommend_{uuid.uuid4().hex[:16]}"
        job = self.bridge.submit_context(
            run_id=run_id,
            context=context,
            job_root=self.state_dir / "recommendation_jobs",
            kernel_ref=self.kernel_ref,
        )
        self.progress("Waiting for Qwen3 optimization reasoning...")
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            status = self.bridge.status(job)
            state = status.get("state")
            if state == "complete":
                result = self.bridge.fetch(job)
                if not isinstance(result, dict):
                    raise ValueError("Qwen recommendation output must be one JSON object.")
                return result
            if state == "failed":
                diagnostic = self.bridge.fetch_error(job)
                raise RuntimeError(self.bridge.format_failure(status, diagnostic))
            self.sleep(self.poll_interval)
        raise TimeoutError("Timed out waiting for Qwen3 recommendation generation.")
