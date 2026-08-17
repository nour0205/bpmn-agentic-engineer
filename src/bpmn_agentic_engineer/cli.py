from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
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
    plan_parser.add_argument("--operation")
    plan_parser.add_argument("--target-element-id")
    plan_parser.add_argument("--target-query")
    plan_parser.add_argument("--source-query", action="append", dest="source_queries")
    plan_parser.add_argument("--process-id")
    plan_parser.add_argument("--new-name")
    plan_parser.add_argument("--new-bpmn-type")
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
    agent_start.add_argument("--operation")
    agent_start.add_argument("--target-element-id")
    agent_start.add_argument("--target-query")
    agent_start.add_argument("--source-query", action="append", dest="source_queries")
    agent_start.add_argument("--process-id")
    agent_start.add_argument("--new-name")
    agent_start.add_argument("--new-bpmn-type")
    agent_start.add_argument("--lane-name")
    agent_start.add_argument("--output-path")
    agent_start.add_argument(
        "--interpretation-mode",
        choices=("deterministic", "qwen3-kaggle"),
        default="deterministic",
    )
    agent_start.add_argument("--kaggle-kernel-ref")
    agent_start.add_argument("--kaggle-accelerator", default="NvidiaTeslaT4")
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
    agent_resume.add_argument("--source-query", action="append", dest="source_queries")
    agent_resume.add_argument("--process-id")
    agent_resume.add_argument("--new-name")
    agent_resume.add_argument("--new-bpmn-type")
    agent_resume.add_argument("--lane-name")
    agent_resume.add_argument("--fetch-llm", action="store_true")
    agent_resume.add_argument("--llm-result-file")
    agent_resume.add_argument("--state-dir", default=".bpmn_agent")

    llm_status = subparsers.add_parser(
        "agent-llm-status",
        help="Read the current Kaggle kernel status for a waiting agent run.",
    )
    llm_status.add_argument("run_id")
    llm_status.add_argument("--state-dir", default=".bpmn_agent")

    agent_status = subparsers.add_parser(
        "agent-status",
        help="Read the persisted state of one BPMN agent run.",
    )
    agent_status.add_argument("run_id")
    agent_status.add_argument("--state-dir", default=".bpmn_agent")

    change_parser = subparsers.add_parser(
        "change",
        help="Run one complete Qwen-assisted BPMN change without handling run IDs.",
    )
    change_parser.add_argument("file")
    change_parser.add_argument("--request")
    change_parser.add_argument("--output")
    change_parser.add_argument(
        "--kaggle-kernel-ref",
        default="nourkouider05/bpmn-qwen3-interpreter",
    )
    change_parser.add_argument("--poll-interval", type=float, default=10.0)
    change_parser.add_argument("--timeout", type=float, default=3600.0)
    change_parser.add_argument("--state-dir", default=".bpmn_agent")
    change_parser.add_argument("--verbose", action="store_true")

    interactive_parser = subparsers.add_parser(
        "interactive",
        help="Apply multiple natural-language changes with automatic BPMN version chaining.",
    )
    interactive_parser.add_argument("file")
    interactive_parser.add_argument("--output-dir")
    interactive_parser.add_argument(
        "--kaggle-kernel-ref",
        default="nourkouider05/bpmn-qwen3-interpreter",
    )
    interactive_parser.add_argument("--poll-interval", type=float, default=10.0)
    interactive_parser.add_argument("--timeout", type=float, default=3600.0)
    interactive_parser.add_argument("--state-dir", default=".bpmn_agent")
    interactive_parser.add_argument("--verbose", action="store_true")

    preview_parser = subparsers.add_parser("preview", help="Generate a side-by-side BPMN change preview.")
    preview_parser.add_argument("before")
    preview_parser.add_argument("after")
    preview_parser.add_argument("--output")
    preview_parser.add_argument("--no-open", action="store_true")
    preview_parser.add_argument("--title")
    preview_parser.add_argument(
        "--presentation",
        action="store_true",
        help="Generate a screenshot-oriented AS-IS / TO-BE presentation.",
    )

    analyze_parser = subparsers.add_parser("analyze", help="Run deterministic read-only BPMN structural analysis.")
    analyze_parser.add_argument("file")
    analyze_parser.add_argument("--json", action="store_true", dest="json_output")
    analyze_parser.add_argument("--output", help="Optional path for the JSON analysis result.")

    return parser


def _product_service(args: argparse.Namespace):
    from bpmn_agentic_engineer.change_service import BpmnChangeService

    return BpmnChangeService(
        args.state_dir,
        kernel_ref=args.kaggle_kernel_ref,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        progress_handler=print,
    )


def _print_plan(state: dict[str, Any]) -> None:
    plan = state.get("plan") or {}
    selected = plan.get("selected_target") or {}
    operations = plan.get("planned_operations") or []
    print("\nPROPOSED CHANGE")
    print("------------------------------")
    if selected:
        print(f"Target: {selected.get('name') or selected.get('id')}")
        if selected.get("lane_name"):
            print(f"Current lane: {selected['lane_name']}")
    for operation in operations:
        parameters = operation.get("parameters") or {}
        print(f"\nOperation: {operation.get('operation')}")
        if parameters.get("name"):
            print(f"Name: {parameters['name']}")
        if parameters.get("new_name"):
            print(f"New name: {parameters['new_name']}")
        if parameters.get("bpmn_type"):
            print(f"BPMN type: {parameters['bpmn_type']}")
        if parameters.get("lane_name"):
            print(f"Lane: {parameters['lane_name']}")


def _clarification_prompt(state: dict[str, Any]) -> dict[str, Any] | str | None:
    from bpmn_agentic_engineer.planning.grounding import normalize_text

    plan = state.get("plan") or {}
    print("\nCLARIFICATION REQUIRED")
    print("------------------------------")
    for question in plan.get("clarification_questions") or ["Which activity do you mean?"]:
        print(question)
    candidates = plan.get("candidate_matches") or []
    for index, candidate in enumerate(candidates, start=1):
        print(f"\n{index}.")
        print(f"Name: {candidate.get('name') or 'unnamed'}")
        print(f"Lane: {candidate.get('lane_name') or 'no lane'}")
    answer = input("> ").strip()
    if not answer:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(candidates):
        candidate = candidates[int(answer) - 1]
        if candidate.get("id"):
            return {"target_element_id": candidate["id"]}
        return str(candidate.get("name"))
    normalized_answer = normalize_text(answer)
    matching_lanes = [
        candidate
        for candidate in candidates
        if candidate.get("lane_name")
        and normalize_text(str(candidate["lane_name"])) in normalized_answer
    ]
    if not matching_lanes:
        answer_tokens = {token for token in normalized_answer.split() if len(token) >= 4}
        scored_lanes = []
        for candidate in candidates:
            lane_name = candidate.get("lane_name")
            if not lane_name:
                continue
            lane_tokens = {
                token for token in normalize_text(str(lane_name)).split() if len(token) >= 4
            }
            overlap = len(answer_tokens & lane_tokens)
            coverage = overlap / len(lane_tokens) if lane_tokens else 0.0
            if overlap >= 2 and coverage >= 0.5:
                scored_lanes.append((coverage, overlap, candidate))
        if scored_lanes:
            best_score = max((coverage, overlap) for coverage, overlap, _ in scored_lanes)
            matching_lanes = [
                candidate
                for coverage, overlap, candidate in scored_lanes
                if (coverage, overlap) == best_score
            ]
    if len(matching_lanes) == 1 and matching_lanes[0].get("id"):
        return {"target_element_id": matching_lanes[0]["id"]}
    if candidates:
        print("Please choose a listed number or name one candidate lane exactly.")
        return _clarification_prompt(state)
    return answer


def _approval_prompt(state: dict[str, Any]) -> bool:
    _print_plan(state)
    return input("\nApprove this modification? [y/N]: ").strip().casefold() in {"y", "yes", "o", "oui"}


def _print_change_result(result: dict[str, Any], *, verbose: bool = False) -> None:
    status = result.get("status")
    if status == "completed":
        validation = result.get("validation") or {}
        print("\nMODIFICATION COMPLETED")
        print("------------------------------")
        print("BPMN modification applied")
        print(f"Structural errors: {validation.get('error_count', 0)}")
        diff = result.get("execution_diff") or {}
        print(f"Added elements: {len(diff.get('added_elements') or [])}")
        print(f"Removed elements: {len(diff.get('removed_elements') or [])}")
        print(f"Renamed elements: {len(diff.get('renamed_elements') or [])}")
        print(f"Output: {result.get('output_file')}")
    elif status == "cancelled":
        print("\nModification cancelled. No BPMN output was created.")
    elif status == "needs_clarification":
        print("\nModification paused: clarification is required.")
    else:
        print(f"\nModification failed: {result.get('error') or status}")
    if verbose:
        _print_json(result)


def _run_change_command(args: argparse.Namespace) -> int:
    source = Path(args.file).expanduser().resolve()
    request = args.request or input("Describe the BPMN modification:\n> ").strip()
    print("\nBPMN Agentic Engineer")
    print(f"Source: {source}")
    print(f"Request: {request}")
    result = _product_service(args).run_change(
        source,
        request,
        output_file=args.output,
        clarification_handler=_clarification_prompt,
        approval_handler=_approval_prompt,
    )
    _print_change_result(result, verbose=args.verbose)
    return 0 if result.get("status") in {"completed", "cancelled"} else 2


def _run_interactive_command(args: argparse.Namespace) -> int:
    from bpmn_agentic_engineer.change_service import BpmnInteractiveSession

    session = BpmnInteractiveSession(
        args.file,
        _product_service(args),
        output_dir=args.output_dir,
    )
    print("BPMN Agentic Engineer")
    print(f"Current: {session.current}")
    while True:
        try:
            command = input("\nbpmn> ").strip()
        except EOFError:
            print()
            return 0
        if not command:
            continue
        if command == ":quit":
            return 0
        if command in {":status", ":path"}:
            print(f"Current: {session.current}")
            continue
        if command == ":history":
            if not session.history:
                print("No successful changes in this session.")
            for index, item in enumerate(session.history, start=1):
                print(f"{index}. {item.get('output_file')}")
            continue
        if command == ":reset":
            session.reset()
            print(f"Reset to: {session.current}")
            continue
        if command.startswith(":"):
            print("Commands: :status, :history, :reset, :path, :quit")
            continue
        previous = session.current
        result = session.apply(
            command,
            clarification_handler=_clarification_prompt,
            approval_handler=_approval_prompt,
        )
        _print_change_result(result, verbose=args.verbose)
        if result.get("status") == "completed":
            print(f"Current BPMN: {session.current}")
            if input("Open before/after preview? [Y/n]: ").strip().casefold() not in {"n", "no", "non"}:
                from bpmn_agentic_engineer.preview import generate_preview
                preview_path, _ = generate_preview(previous, session.current)
                print(f"Preview generated: {preview_path.as_uri()}")


def _run_preview_command(args: argparse.Namespace) -> int:
    from bpmn_agentic_engineer.preview import generate_preview
    path, diff = generate_preview(
        args.before,
        args.after,
        args.output,
        title=args.title,
        open_browser=not args.no_open,
        presentation=args.presentation,
    )
    print("BPMN CHANGE PREVIEW\n-------------------")
    print(f"Before: {Path(args.before).name}\nAfter: {Path(args.after).name}")
    print(f"\nAdded: {len(diff['added_elements'])}\nRemoved: {len(diff['removed_elements'])}\nRenamed: {len(diff['renamed_elements'])}")
    print(f"Added flows: {len(diff['added_sequence_flows'])}\nRemoved flows: {len(diff['removed_sequence_flows'])}")
    print(f"\nPreview:\n{path.as_uri()}")
    print("Opening browser..." if not args.no_open else "Browser opening disabled.")
    return 0


def _run_analyze_command(args: argparse.Namespace) -> int:
    from bpmn_agentic_engineer.analysis import BpmnAnalyzer
    result = BpmnAnalyzer().analyze(args.file)
    payload = result.to_dict()
    if args.output:
        _write_json(args.output, payload)
    if args.json_output:
        _print_json(payload)
        return 0
    metrics = result.metrics
    print("BPMN PROCESS ANALYSIS\n=====================")
    print(f"\nProcess:\n{result.process_name or Path(result.source_path).stem}")
    print("\nSTRUCTURE\n---------")
    for label, key in (("Flow nodes", "total_flow_nodes"), ("Sequence flows", "sequence_flows"),
                       ("Tasks", "tasks"), ("User tasks", "user_tasks"), ("Service tasks", "service_tasks"),
                       ("Gateways", "gateways"), ("Lanes", "lanes")):
        print(f"{label}: {metrics[key]}")
    print("\nGRAPH\n-----")
    print(f"Lane handoffs: {metrics['lane_handoffs']}")
    print(f"Cycles: {metrics['cycles']}")
    print(f"Longest structural path: {metrics['longest_structural_path']} nodes")
    print("\nSTRUCTURAL FINDINGS\n-------------------")
    if not result.findings:
        print("No deterministic structural findings.")
    for finding in result.findings:
        print(f"\n[{finding.severity.upper()}] {finding.title}")
        if finding.element_names:
            print(" -> ".join(finding.element_names))
        print(f"Evidence: {finding.evidence}")
    print("\nVALIDATION\n----------")
    print(f"Errors: {result.validation_summary['error_count']}")
    if args.output:
        print(f"JSON: {Path(args.output).expanduser().resolve()}")
    return 0


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
            operation=args.operation,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            source_queries=args.source_queries,
            process_id=args.process_id,
            new_name=args.new_name,
            new_bpmn_type=args.new_bpmn_type,
            lane_name=args.lane_name,
            output_path=args.output_path,
            interpretation_mode=args.interpretation_mode.replace("-", "_"),
            kaggle_kernel_ref=args.kaggle_kernel_ref,
            kaggle_accelerator=args.kaggle_accelerator,
        )

    if args.command == "agent-resume":
        return _agent_service(args.state_dir).resume(
            args.run_id,
            approved=args.approval,
            cancelled=args.cancelled,
            output_path=args.output_path,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            source_queries=args.source_queries,
            process_id=args.process_id,
            new_name=args.new_name,
            new_bpmn_type=args.new_bpmn_type,
            lane_name=args.lane_name,
            fetch_llm=args.fetch_llm,
            llm_result_file=args.llm_result_file,
        )

    if args.command == "agent-llm-status":
        return _agent_service(args.state_dir).llm_status(args.run_id)

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
            operation=args.operation,
            target_element_id=args.target_element_id,
            target_query=args.target_query,
            source_queries=args.source_queries,
            process_id=args.process_id,
            new_name=args.new_name,
            new_bpmn_type=args.new_bpmn_type,
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
        if args.command == "change":
            sys.exit(_run_change_command(args))
        if args.command == "interactive":
            sys.exit(_run_interactive_command(args))
        if args.command == "preview":
            sys.exit(_run_preview_command(args))
        if args.command == "analyze":
            sys.exit(_run_analyze_command(args))
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
