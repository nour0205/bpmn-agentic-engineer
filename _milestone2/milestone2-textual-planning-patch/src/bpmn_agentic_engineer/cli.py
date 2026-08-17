from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bpmn-agent",
        description="Read-only BPMN inspection and change-planning tools.",
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
    plan_parser.add_argument("request")
    plan_parser.add_argument("--target-element-id")
    plan_parser.add_argument("--target-query")
    plan_parser.add_argument("--process-id")
    plan_parser.add_argument("--new-name")
    plan_parser.add_argument("--lane-name")

    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
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
        return ChangePlanner(document, inspector).plan(
            args.request,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            process_id=args.process_id,
            new_name=args.new_name,
            lane_name=args.lane_name,
        )

    raise RuntimeError(f"Unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        _print_json(run(args))
    except (FileNotFoundError, ValueError, KeyError) as exc:
        _print_json({"error": str(exc)})
        sys.exit(2)


if __name__ == "__main__":
    main()
