from __future__ import annotations

from datetime import datetime, timezone
import operator
from typing import Annotated, Any, Literal, TypedDict


AgentStatus = Literal[
    "received",
    "inspecting",
    "submitting_llm",
    "waiting_for_llm",
    "interpreted",
    "needs_clarification",
    "waiting_for_approval",
    "executing",
    "validating",
    "repairing",
    "completed",
    "cancelled",
    "failed",
]

InterpretationMode = Literal["deterministic", "qwen3_kaggle"]


class AgentState(TypedDict, total=False):
    """Serializable state persisted by LangGraph for one BPMN agent run."""

    run_id: str
    file_path: str
    request_text: str
    operation: str | None
    target_element_id: str | None
    target_query: str | None
    process_id: str | None
    new_name: str | None
    lane_name: str | None
    output_path: str | None

    interpretation_mode: InterpretationMode
    kaggle_kernel_ref: str | None
    kaggle_accelerator: str
    llm_job_root: str
    llm_job: dict[str, Any]
    llm_interpretation: dict[str, Any]
    llm_error: str | None

    status: AgentStatus
    inspection: dict[str, Any]
    baseline_validation: dict[str, Any]
    plan: dict[str, Any]
    approved: bool | None
    approved_plan_checksum: str | None
    execution_result: dict[str, Any]
    final_validation: dict[str, Any]
    repair_attempts: int
    error: str | None

    history: Annotated[list[dict[str, Any]], operator.add]


def history_event(stage: str, status: str, message: str) -> dict[str, Any]:
    """Create one JSON-serializable audit event."""
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": status,
        "message": message,
    }
