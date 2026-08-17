from __future__ import annotations

from .state import AgentState


def after_inspection(state: AgentState) -> str:
    if state.get("status") == "failed":
        return "end"
    if (
        state.get("interpretation_mode") == "qwen3_kaggle"
        and not state.get("llm_interpretation")
        and not state.get("operation")
    ):
        return "interpret"
    return "plan"


def after_llm_submission(state: AgentState) -> str:
    return "wait" if state.get("status") == "waiting_for_llm" else "end"


def after_llm_gate(state: AgentState) -> str:
    return "plan" if state.get("status") == "interpreted" else "end"


def after_planning(state: AgentState) -> str:
    status = state.get("status")
    if status == "needs_clarification":
        return "clarify"
    if status == "waiting_for_approval":
        return "approve"
    return "end"


def after_clarification(state: AgentState) -> str:
    return "inspect" if state.get("status") == "received" else "end"


def after_approval(state: AgentState) -> str:
    return "execute" if state.get("status") == "executing" else "end"


def after_execution(state: AgentState) -> str:
    return "validate" if state.get("status") == "validating" else "end"


def after_validation(state: AgentState) -> str:
    return "repair" if state.get("status") == "repairing" else "end"
