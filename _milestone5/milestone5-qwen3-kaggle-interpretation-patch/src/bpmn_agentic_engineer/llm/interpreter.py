from __future__ import annotations

from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument

from .context import CompactContextBuilder
from .schema import LlmInterpretation


class InterpretationValidator:
    """Validate Qwen output and translate a safe process alias locally."""

    def validate(
        self,
        document: BpmnDocument,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context = CompactContextBuilder(document).build()
        interpretation = LlmInterpretation.from_dict(
            payload,
            allowed_process_aliases=set(context.process_alias_to_id),
        )
        process_id = (
            context.process_alias_to_id.get(interpretation.process_alias)
            if interpretation.process_alias
            else None
        )
        return {
            "interpretation": interpretation.to_dict(),
            "planner_hints": {
                "operation": interpretation.operation,
                "target_query": interpretation.target_query,
                "process_id": process_id,
                "new_name": interpretation.new_name,
                "lane_name": interpretation.lane_name,
            },
        }
