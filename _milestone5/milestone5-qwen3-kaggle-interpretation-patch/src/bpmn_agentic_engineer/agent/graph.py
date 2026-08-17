from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes import AgentNodes
from .routing import (
    after_approval,
    after_clarification,
    after_execution,
    after_inspection,
    after_llm_gate,
    after_llm_submission,
    after_planning,
    after_validation,
)
from .state import AgentState


def build_agent_graph(checkpointer: Any):
    """Build the stable, resumable LangGraph workflow."""
    nodes = AgentNodes()
    builder = StateGraph(AgentState)

    builder.add_node("inspect_source", nodes.inspect_source)
    builder.add_node("submit_llm", nodes.submit_llm)
    builder.add_node("llm_gate", nodes.llm_gate)
    builder.add_node("plan_change", nodes.plan_change)
    builder.add_node("clarification_gate", nodes.clarification_gate)
    builder.add_node("approval_gate", nodes.approval_gate)
    builder.add_node("execute_plan", nodes.execute_plan)
    builder.add_node("validate_output", nodes.validate_output)
    builder.add_node("repair_boundary", nodes.repair_boundary)

    builder.add_edge(START, "inspect_source")
    builder.add_conditional_edges(
        "inspect_source",
        after_inspection,
        {"interpret": "submit_llm", "plan": "plan_change", "end": END},
    )
    builder.add_conditional_edges(
        "submit_llm",
        after_llm_submission,
        {"wait": "llm_gate", "end": END},
    )
    builder.add_conditional_edges(
        "llm_gate",
        after_llm_gate,
        {"plan": "plan_change", "end": END},
    )
    builder.add_conditional_edges(
        "plan_change",
        after_planning,
        {"clarify": "clarification_gate", "approve": "approval_gate", "end": END},
    )
    builder.add_conditional_edges(
        "clarification_gate",
        after_clarification,
        {"inspect": "inspect_source", "end": END},
    )
    builder.add_conditional_edges(
        "approval_gate",
        after_approval,
        {"execute": "execute_plan", "end": END},
    )
    builder.add_conditional_edges(
        "execute_plan",
        after_execution,
        {"validate": "validate_output", "end": END},
    )
    builder.add_conditional_edges(
        "validate_output",
        after_validation,
        {"repair": "repair_boundary", "end": END},
    )
    builder.add_edge("repair_boundary", END)
    return builder.compile(checkpointer=checkpointer)
