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
        description="BPMN inspection, safe planning and approved execution tools.",
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

    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
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
