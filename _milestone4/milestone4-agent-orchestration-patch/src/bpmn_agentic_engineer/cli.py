from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bpmn-agent",
        description="BPMN inspection, planning, approved execution and agent orchestration.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a BPMN file.")
    inspect_parser.add_argument("file")
    inspect_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Do not include all elements and flows.",
    )

    find_parser = subparsers.add_parser("find", help="Find BPMN elements by name, ID or lane.")
    find_parser.add_argument("file")
    find_parser.add_argument("query")
    find_parser.add_argument("--limit", type=int, default=10)

    context_parser = subparsers.add_parser("context", help="Get local context for one element.")
    context_parser.add_argument("file")
    context_parser.add_argument("element_id")

    path_parser = subparsers.add_parser("path", help="Find a directed path between two elements.")
    path_parser.add_argument("file")
    path_parser.add_argument("source_id")
    path_parser.add_argument("target_id")

    validate_parser = subparsers.add_parser("validate", help="Run basic structural validation.")
    validate_parser.add_argument("file")

    plan_parser = subparsers.add_parser(
        "plan",
        help="Produce a read-only modification plan from a natural-language request.",
    )
    plan_parser.add_argument("file")
    plan_parser.add_argument(
        "request",
        nargs="+",
        help="Natural-language change request.",
    )
    plan_parser.add_argument("--target-element-id")
    plan_parser.add_argument("--target-query")
    plan_parser.add_argument("--process-id")
    plan_parser.add_argument("--new-name")
    plan_parser.add_argument("--lane-name")
    plan_parser.add_argument(
        "--save-plan",
        help="Optional JSON path where the checksummed plan will be saved.",
    )

    execute_parser = subparsers.add_parser(
        "execute",
        help="Execute an approved checksummed plan on a new BPMN file.",
    )
    execute_parser.add_argument("plan_file", help="Path to the saved plan JSON.")
    execute_parser.add_argument("output_file", help="New .bpmn or .xml output path.")
    execute_parser.add_argument(
        "--approved",
        action="store_true",
        help="Confirm that the exact saved plan was reviewed and approved.",
    )

    agent_start = subparsers.add_parser(
        "agent-start",
        help="Start a durable BPMN workflow and pause for clarification or approval.",
    )
    agent_start.add_argument("file")
    agent_start.add_argument("request", nargs="+")
    agent_start.add_argument("--target-element-id")
    agent_start.add_argument("--target-query")
    agent_start.add_argument("--process-id")
    agent_start.add_argument("--new-name")
    agent_start.add_argument("--lane-name")
    agent_start.add_argument("--output-path")
    agent_start.add_argument("--state-dir", default=".bpmn_agent")

    agent_resume = subparsers.add_parser(
        "agent-resume",
        help="Resume a paused BPMN agent run with clarification or approval.",
    )
    agent_resume.add_argument("run_id")
    approval = agent_resume.add_mutually_exclusive_group()
    approval.add_argument("--approved", dest="approval", action="store_const", const=True)
    approval.add_argument("--rejected", dest="approval", action="store_const", const=False)
    agent_resume.set_defaults(approval=None)
    agent_resume.add_argument("--cancelled", action="store_true")
    agent_resume.add_argument("--output-path")
    agent_resume.add_argument("--target-element-id")
    agent_resume.add_argument("--target-query")
    agent_resume.add_argument("--process-id")
    agent_resume.add_argument("--new-name")
    agent_resume.add_argument("--lane-name")
    agent_resume.add_argument("--state-dir", default=".bpmn_agent")

    agent_status = subparsers.add_parser(
        "agent-status",
        help="Read the persisted state of one BPMN agent run.",
    )
    agent_status.add_argument("run_id")
    agent_status.add_argument("--state-dir", default=".bpmn_agent")

    return parser


def _agent_service(state_dir: str):
    try:
        from bpmn_agentic_engineer.agent import AgentService
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Agent dependencies are missing. Run: uv sync --extra all"
        ) from exc
    return AgentService(state_dir)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "agent-start":
        request_text = " ".join(args.request) if isinstance(args.request, list) else args.request
        return _agent_service(args.state_dir).start(
            args.file,
            request_text,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            process_id=args.process_id,
            new_name=args.new_name,
            lane_name=args.lane_name,
            output_path=args.output_path,
        )

    if args.command == "agent-resume":
        return _agent_service(args.state_dir).resume(
            args.run_id,
            approved=args.approval,
            cancelled=args.cancelled,
            output_path=args.output_path,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            process_id=args.process_id,
            new_name=args.new_name,
            lane_name=args.lane_name,
        )

    if args.command == "agent-status":
        return _agent_service(args.state_dir).status(args.run_id)

    if args.command == "execute":
        plan_path = Path(args.plan_file).expanduser().resolve()
        if not plan_path.exists():
            raise FileNotFoundError(f"Plan file not found: {plan_path}")
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid plan JSON: {exc}") from exc
        if not isinstance(plan, dict):
            raise ValueError("The plan JSON must contain one object.")
        return BpmnPlanExecutor().execute(
            plan,
            args.output_file,
            approved=args.approved,
        )

    document = BpmnDocument(args.file)
    inspector = ProcessInspector(document)

    if args.command == "inspect":
        return inspector.summary(include_elements=not args.summary_only)
    if args.command == "find":
        return {"query": args.query, "matches": inspector.find_elements(args.query, args.limit)}
    if args.command == "context":
        return inspector.element_context(args.element_id)
    if args.command == "path":
        return inspector.find_path(args.source_id, args.target_id)
    if args.command == "validate":
        return BasicValidator(document).validate()
    if args.command == "plan":
        request_text = " ".join(args.request) if isinstance(args.request, list) else args.request
        result = ChangePlanner(document, inspector).plan(
            request_text,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            process_id=args.process_id,
            new_name=args.new_name,
            lane_name=args.lane_name,
        )
        if args.save_plan:
            saved_path = _write_json(args.save_plan, result)
            result = {**result, "saved_plan": str(saved_path)}
        return result

    raise RuntimeError(f"Unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        _print_json(run(args))
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        ValueError,
    ) as exc:
        _print_json({"error": str(exc)})
        sys.exit(2)


if __name__ == "__main__":
    main()
