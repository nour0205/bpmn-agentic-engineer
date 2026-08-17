from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


mcp = MCPServer("BPMN Engineering")


def _load(file_path: str) -> tuple[BpmnDocument, ProcessInspector]:
    path = Path(file_path).expanduser().resolve()
    document = BpmnDocument(path)
    return document, ProcessInspector(document)


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE_COPY = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)


@mcp.tool(title="Inspect BPMN", annotations=READ_ONLY)
def inspect_bpmn(
    file_path: Annotated[
        str,
        Field(description="Absolute or relative path to a BPMN XML file."),
    ],
    include_elements: bool = True,
) -> dict:
    """Return processes, element counts, lanes, flow nodes and sequence flows."""
    _, inspector = _load(file_path)
    return inspector.summary(include_elements=include_elements)


@mcp.tool(title="Find BPMN elements", annotations=READ_ONLY)
def find_bpmn_elements(
    file_path: Annotated[str, Field(description="Path to a BPMN XML file.")],
    query: Annotated[
        str,
        Field(min_length=1, description="Task, event, gateway, lane name or ID."),
    ],
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
) -> dict:
    """Search flow nodes by label, identifier, BPMN type and lane."""
    _, inspector = _load(file_path)
    return {"query": query, "matches": inspector.find_elements(query, limit=limit)}


@mcp.tool(title="Get BPMN element context", annotations=READ_ONLY)
def get_bpmn_element_context(
    file_path: Annotated[str, Field(description="Path to a BPMN XML file.")],
    element_id: Annotated[
        str,
        Field(min_length=1, description="Exact BPMN flow-node ID."),
    ],
) -> dict:
    """Return one element with its predecessors, successors and connecting flows."""
    _, inspector = _load(file_path)
    return inspector.element_context(element_id)


@mcp.tool(title="Find BPMN path", annotations=READ_ONLY)
def find_bpmn_path(
    file_path: Annotated[str, Field(description="Path to a BPMN XML file.")],
    source_id: Annotated[str, Field(min_length=1)],
    target_id: Annotated[str, Field(min_length=1)],
) -> dict:
    """Find a directed path between two BPMN flow nodes."""
    _, inspector = _load(file_path)
    return inspector.find_path(source_id, target_id)


@mcp.tool(title="Validate BPMN structure", annotations=READ_ONLY)
def validate_bpmn(
    file_path: Annotated[str, Field(description="Path to a BPMN XML file.")],
) -> dict:
    """Run deterministic duplicate-ID, reference, boundary and reachability checks."""
    document, _ = _load(file_path)
    return BasicValidator(document).validate()


@mcp.tool(title="Plan BPMN change", annotations=READ_ONLY)
def plan_bpmn_change(
    file_path: Annotated[str, Field(description="Path to a BPMN XML file.")],
    request: Annotated[
        str,
        Field(min_length=1, description="Natural-language BPMN change request."),
    ],
    operation: Annotated[
        str | None,
        Field(description="Optional explicit operation hint."),
    ] = None,
    target_element_id: Annotated[
        str | None,
        Field(description="Optional exact target BPMN element ID."),
    ] = None,
    target_query: Annotated[
        str | None,
        Field(description="Optional explicit target name/search query."),
    ] = None,
    source_queries: Annotated[
        list[str] | None,
        Field(description="Visible labels of consecutive source tasks to replace."),
    ] = None,
    process_id: Annotated[
        str | None,
        Field(description="Optional process ID used to disambiguate variants."),
    ] = None,
    new_name: Annotated[
        str | None,
        Field(description="Optional explicit name for a new or renamed element."),
    ] = None,
    new_bpmn_type: Annotated[
        str | None,
        Field(description="Optional BPMN type for a newly created replacement task."),
    ] = None,
    lane_name: Annotated[
        str | None,
        Field(description="Optional actor/lane filter."),
    ] = None,
) -> dict:
    """Produce a checksummed read-only atomic change plan."""
    document, inspector = _load(file_path)
    return ChangePlanner(document, inspector).plan(
        request,
        operation=operation,
        target_element_id=target_element_id,
        target_query=target_query,
        source_queries=source_queries,
        process_id=process_id,
        new_name=new_name,
        new_bpmn_type=new_bpmn_type,
        lane_name=lane_name,
    )


@mcp.tool(title="Execute approved BPMN plan", annotations=WRITE_COPY)
def execute_bpmn_plan(
    plan: Annotated[
        dict[str, Any],
        Field(description="Exact checksummed plan returned by plan_bpmn_change."),
    ],
    output_path: Annotated[
        str,
        Field(description="New .bpmn or .xml output path; source is never overwritten."),
    ],
    approved: Annotated[
        bool,
        Field(description="Must be true after the exact plan has been reviewed."),
    ] = False,
) -> dict:
    """Execute an approved plan on a new file, validate it and return a diff."""
    return BpmnPlanExecutor().execute(plan, output_path, approved=approved)


STATEFUL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)


def _agent_service(state_dir: str):
    try:
        from bpmn_agentic_engineer.agent import AgentService
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Agent dependencies are missing. Install the project's 'all' extra."
        ) from exc
    return AgentService(state_dir)


@mcp.tool(title="Run BPMN engineering agent", annotations=STATEFUL)
def run_bpmn_agent(
    file_path: Annotated[str, Field(description="Path to a BPMN XML file.")],
    request: Annotated[
        str,
        Field(min_length=1, description="Natural-language BPMN change request."),
    ],
    operation: Annotated[
        str | None,
        Field(description="Optional explicit deterministic operation hint."),
    ] = None,
    output_path: Annotated[
        str | None,
        Field(description="Optional output copy path used after later approval."),
    ] = None,
    target_element_id: Annotated[
        str | None,
        Field(description="Optional exact target BPMN element ID."),
    ] = None,
    target_query: Annotated[
        str | None,
        Field(description="Optional explicit target name/search query."),
    ] = None,
    source_queries: Annotated[
        list[str] | None,
        Field(description="Visible labels of consecutive source tasks to replace."),
    ] = None,
    process_id: Annotated[
        str | None,
        Field(description="Optional process ID used to disambiguate variants."),
    ] = None,
    new_name: Annotated[
        str | None,
        Field(description="Optional explicit name for a new or renamed element."),
    ] = None,
    new_bpmn_type: Annotated[
        str | None,
        Field(description="Optional BPMN type for the new consolidated task."),
    ] = None,
    lane_name: Annotated[
        str | None,
        Field(description="Optional actor/lane filter."),
    ] = None,
    interpretation_mode: Annotated[
        str,
        Field(description="deterministic or qwen3_kaggle."),
    ] = "deterministic",
    kaggle_kernel_ref: Annotated[
        str | None,
        Field(description="Kaggle kernel reference owner/kernel-slug for Qwen3 mode."),
    ] = None,
    kaggle_accelerator: Annotated[
        str,
        Field(description="Kaggle accelerator ID; NvidiaTeslaT4 is recommended."),
    ] = "NvidiaTeslaT4",
    state_dir: Annotated[
        str,
        Field(description="Directory containing durable agent checkpoints."),
    ] = ".bpmn_agent",
) -> dict:
    """Start a durable workflow and pause for clarification or human approval."""
    return _agent_service(state_dir).start(
        file_path,
        request,
        operation=operation,
        output_path=output_path,
        target_element_id=target_element_id,
        target_query=target_query,
        source_queries=source_queries,
        process_id=process_id,
        new_name=new_name,
        new_bpmn_type=new_bpmn_type,
        lane_name=lane_name,
        interpretation_mode=interpretation_mode.replace("-", "_"),
        kaggle_kernel_ref=kaggle_kernel_ref,
        kaggle_accelerator=kaggle_accelerator,
    )


@mcp.tool(title="Resume BPMN engineering agent", annotations=WRITE_COPY)
def resume_bpmn_agent(
    run_id: Annotated[str, Field(min_length=1, description="Persisted agent run ID.")],
    approved: Annotated[
        bool | None,
        Field(description="Set true to approve or false to reject a waiting plan."),
    ] = None,
    cancelled: Annotated[
        bool,
        Field(description="Cancel a clarification or approval checkpoint."),
    ] = False,
    output_path: Annotated[
        str | None,
        Field(description="Output BPMN copy path required before approval."),
    ] = None,
    target_element_id: Annotated[
        str | None,
        Field(description="Clarification: exact target element ID."),
    ] = None,
    target_query: Annotated[
        str | None,
        Field(description="Clarification: explicit target query."),
    ] = None,
    source_queries: Annotated[
        list[str] | None,
        Field(description="Clarification: consecutive source task labels."),
    ] = None,
    process_id: Annotated[
        str | None,
        Field(description="Clarification: process variant ID."),
    ] = None,
    new_name: Annotated[
        str | None,
        Field(description="Clarification: new task or element name."),
    ] = None,
    new_bpmn_type: Annotated[
        str | None,
        Field(description="Clarification: BPMN type for a new task."),
    ] = None,
    lane_name: Annotated[
        str | None,
        Field(description="Clarification: actor/lane name."),
    ] = None,
    fetch_llm: Annotated[
        bool,
        Field(description="Fetch the completed Qwen3 interpretation from Kaggle."),
    ] = False,
    llm_result_file: Annotated[
        str | None,
        Field(description="Optional local JSON result file instead of fetching Kaggle."),
    ] = None,
    state_dir: Annotated[
        str,
        Field(description="Directory containing durable agent checkpoints."),
    ] = ".bpmn_agent",
) -> dict:
    """Resume the exact persisted graph state; approved plans are not regenerated."""
    return _agent_service(state_dir).resume(
        run_id,
        approved=approved,
        cancelled=cancelled,
        output_path=output_path,
        target_element_id=target_element_id,
        target_query=target_query,
        source_queries=source_queries,
        process_id=process_id,
        new_name=new_name,
        new_bpmn_type=new_bpmn_type,
        lane_name=lane_name,
        fetch_llm=fetch_llm,
        llm_result_file=llm_result_file,
    )


@mcp.tool(title="Get BPMN agent LLM status", annotations=READ_ONLY)
def get_bpmn_agent_llm_status(
    run_id: Annotated[str, Field(min_length=1, description="Persisted agent run ID.")],
    state_dir: Annotated[
        str,
        Field(description="Directory containing durable agent checkpoints."),
    ] = ".bpmn_agent",
) -> dict:
    """Return the current Kaggle status for a Qwen3 interpretation job."""
    return _agent_service(state_dir).llm_status(run_id)


@mcp.tool(title="Get BPMN agent run", annotations=READ_ONLY)
def get_bpmn_agent_run(
    run_id: Annotated[str, Field(min_length=1, description="Persisted agent run ID.")],
    state_dir: Annotated[
        str,
        Field(description="Directory containing durable agent checkpoints."),
    ] = ".bpmn_agent",
) -> dict:
    """Return the latest durable state for one BPMN agent run."""
    return _agent_service(state_dir).status(run_id)
