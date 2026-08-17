from __future__ import annotations

from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument

from .context import CompactContextBuilder
from .normalization import enforce_generic_target_ambiguity, explicit_catalogue_scope
from .schema import LlmInterpretation


class InterpretationValidator:
    """Validate Qwen output and translate a safe process alias locally."""

    def validate(
        self,
        document: BpmnDocument,
        payload: dict[str, Any],
        *,
        request_text: str | None = None,
    ) -> dict[str, Any]:
        context = CompactContextBuilder(document).build()
        if request_text:
            payload = enforce_generic_target_ambiguity(
                request_text,
                context.payload,
                payload,
            )
            if payload.get("operation") in {"rename_element", "remove_element"}:
                lane_name, process_alias = explicit_catalogue_scope(
                    request_text,
                    context.payload,
                )
                payload = dict(payload)
                payload["lane_name"] = lane_name
                payload["process_alias"] = process_alias
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
                "source_queries": list(interpretation.source_queries),
                "process_id": process_id,
                "new_name": interpretation.new_name,
                "new_bpmn_type": interpretation.new_bpmn_type,
                "lane_name": interpretation.lane_name,
            },
        }
