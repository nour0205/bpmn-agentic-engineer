from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.validation import BasicValidator


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bpmn-agent",
        description="Qwen-assisted, deterministic and human-approved BPMN transformation.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate BPMN structure and BPMN-DI.")
    validate.add_argument("file")
    analyze = commands.add_parser("analyze", help="Run deterministic read-only analysis.")
    analyze.add_argument("file")
    analyze.add_argument("--json", action="store_true", dest="json_output")
    analyze.add_argument("--output")
    recommend = commands.add_parser(
        "recommend", help="Generate evidence-grounded optimization recommendations."
    )
    recommend.add_argument("file")
    recommend.add_argument(
        "--goal", help="Optional optimization objective used for prioritization."
    )
    recommend.add_argument("--json", action="store_true", dest="json_output")
    recommend.add_argument("--show-low-confidence", action="store_true")
    _add_agent_options(recommend)
    change = commands.add_parser("change", help="Apply recommendations and write one final BPMN.")
    change.add_argument("file")
    change.add_argument("--request", action="append", help="Repeat for multiple recommendations.")
    change.add_argument(
        "--requests-file", help="UTF-8 file with one recommendation per non-empty line."
    )
    change.add_argument("--output", help="Defaults to generated/<original filename>.")
    change.add_argument(
        "--force", action="store_true", help="Overwrite the final output if it exists."
    )
    _add_agent_options(change)
    interactive = commands.add_parser(
        "interactive", help="Build one final BPMN through an approved session."
    )
    interactive.add_argument("file")
    interactive.add_argument("--output", help="Defaults to generated/<original filename>.")
    interactive.add_argument(
        "--force", action="store_true", help="Overwrite the final output if it exists."
    )
    _add_agent_options(interactive)
    return parser


def _add_agent_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--kaggle-kernel-ref",
        default=os.environ.get("BPMN_AGENT_KAGGLE_KERNEL", "nourkouider05/bpmn-qwen3-interpreter"),
    )
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--state-dir", default=".bpmn_agent")
    parser.add_argument("--verbose", action="store_true")


def _service(args: argparse.Namespace):
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
    target = plan.get("selected_target") or {}
    print("\nPROPOSED CHANGE\n------------------------------")
    if target:
        print(f"Target: {target.get('name') or target.get('id')}")
        print(f"Element ID: {target.get('id')}")
        print(f"Process ID: {target.get('process_id')}")
        print(f"Lane: {target.get('lane_name') or 'no lane'}")
    for operation in plan.get("planned_operations") or []:
        print(f"\nOperation: {operation.get('operation')}")
        for key, label in (
            ("name", "Name"),
            ("new_name", "New name"),
            ("bpmn_type", "BPMN type"),
            ("lane_name", "Lane"),
        ):
            value = (operation.get("parameters") or {}).get(key)
            if value:
                print(f"{label}: {value}")
    if plan.get("plan_checksum"):
        print(f"\nPlan checksum: {plan['plan_checksum']}")


def _clarification_prompt(state: dict[str, Any]) -> dict[str, Any] | str | None:
    from bpmn_agentic_engineer.planning.grounding import normalize_text

    plan = state.get("plan") or {}
    print("\nCLARIFICATION REQUIRED\n------------------------------")
    for question in plan.get("clarification_questions") or ["Which activity do you mean?"]:
        print(question)
    candidates = plan.get("candidate_matches") or []
    for index, candidate in enumerate(candidates, 1):
        print(f"{index}. {candidate.get('name') or 'unnamed'}")
        print(f"   ID: {candidate.get('id') or 'unknown'}")
        print(f"   Process: {candidate.get('process_id') or 'unknown'}")
        print(f"   Lane: {candidate.get('lane_name') or 'no lane'}")
    answer = input("> ").strip()
    if not answer:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(candidates):
        candidate = candidates[int(answer) - 1]
        return (
            {"target_element_id": candidate["id"]}
            if candidate.get("id")
            else str(candidate.get("name"))
        )
    normalized = normalize_text(answer)
    matches = [
        c
        for c in candidates
        if c.get("lane_name") and normalize_text(str(c["lane_name"])) in normalized
    ]
    if not matches:
        tokens = {token for token in normalized.split() if len(token) >= 4}
        scored = []
        for candidate in candidates:
            lane = candidate.get("lane_name")
            lane_tokens = (
                {t for t in normalize_text(str(lane)).split() if len(t) >= 4} if lane else set()
            )
            overlap = len(tokens & lane_tokens)
            coverage = overlap / len(lane_tokens) if lane_tokens else 0
            if overlap >= 2 and coverage >= 0.5:
                scored.append((coverage, overlap, candidate))
        if scored:
            best = max((coverage, overlap) for coverage, overlap, _ in scored)
            matches = [
                candidate for coverage, overlap, candidate in scored if (coverage, overlap) == best
            ]
    if len(matches) == 1 and matches[0].get("id"):
        return {"target_element_id": matches[0]["id"]}
    if candidates:
        print("Please choose a listed number or name one candidate lane exactly.")
        return _clarification_prompt(state)
    return answer


def _approve(state: dict[str, Any]) -> bool:
    _print_plan(state)
    return input("\nApprove this exact modification? [y/N]: ").strip().casefold() in {
        "y",
        "yes",
        "o",
        "oui",
    }


def _print_result(result: dict[str, Any], verbose: bool = False, *, final: bool = False) -> None:
    status = result.get("status")
    if status == "completed":
        validation = result.get("validation") or {}
        diff = result.get("execution_diff") or {}
        print("\nFINAL BPMN CREATED" if final else "\nMODIFICATION APPLIED")
        print("------------------------------")
        print(f"Structural errors: {validation.get('error_count', 0)}")
        print(f"Added elements: {len(diff.get('added_elements') or [])}")
        print(f"Removed elements: {len(diff.get('removed_elements') or [])}")
        print(f"Renamed elements: {len(diff.get('renamed_elements') or [])}")
        if final:
            print(f"Approved modifications: {result.get('approved_modifications', 0)}")
            print(f"Output: {result.get('output_file')}")
        else:
            print(f"Session modifications: {result.get('session_changes', 0)}")
            print("Working model updated: YES")
    elif status == "cancelled":
        print("\nModification rejected. The working BPMN was not changed.")
    elif status == "collision":
        print(f"\nFinal BPMN was not written: {result.get('error')}")
    elif status == "needs_clarification":
        print("\nModification paused safely: clarification is required.")
    else:
        print(f"\nModification failed: {result.get('error') or status}")
    if verbose:
        _print_json(result)


def _requests(args: argparse.Namespace) -> list[str]:
    requests = list(args.request or [])
    if args.requests_file:
        requests.extend(
            line.strip()
            for line in Path(args.requests_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if not requests:
        request = input("Describe the BPMN modification:\n> ").strip()
        if request:
            requests.append(request)
    if not requests:
        raise ValueError("At least one BPMN recommendation is required.")
    return requests


def _confirm_overwrite(path: Path) -> bool:
    return input(
        f"Final output already exists: {path}\nOverwrite it? [y/N]: "
    ).strip().casefold() in {"y", "yes", "o", "oui"}


def _change(args: argparse.Namespace) -> int:
    requests = _requests(args)
    interactive = sys.stdin.isatty()
    session = _service(args).start_session(args.file, args.output)
    failed = False
    try:
        for index, request in enumerate(requests, 1):
            print(f"\nREQUEST {index}/{len(requests)}\n==============================")
            result = session.apply(
                request,
                clarification_handler=_clarification_prompt if interactive else None,
                approval_handler=_approve if interactive else None,
            )
            _print_result(result, args.verbose)
            failed |= result.get("status") not in {"completed", "cancelled"}
        if not session.history:
            print("\nNo recommendation was approved; no final BPMN was written.")
            return 0 if not failed else 2
        final = session.finish(
            force=args.force,
            overwrite_handler=_confirm_overwrite if interactive else None,
        )
        _print_result(final, args.verbose, final=True)
        return 0 if final.get("status") == "completed" and not failed else 2
    finally:
        session.close()


def _interactive(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        raise RuntimeError("Interactive mode requires a terminal.")
    session = _service(args).start_session(args.file, args.output)
    print(
        f"BPMN Agentic Engineer\nSource: {session.original.name}\nFinal output: {session.final_output}"
    )
    print("Commands: :status, :history, :reset, :finish, :quit")
    try:
        while True:
            try:
                command = input("\nbpmn> ").strip()
            except EOFError:
                command = ":quit"
            if not command:
                continue
            if command == ":quit":
                if session.unsaved:
                    save = (
                        input(
                            f"There are {len(session.history)} unsaved approved modifications. "
                            "Save final BPMN before quitting? [Y/n]: "
                        )
                        .strip()
                        .casefold()
                    )
                    if save not in {"n", "no", "non"}:
                        result = session.finish(
                            force=args.force, overwrite_handler=_confirm_overwrite
                        )
                        _print_result(result, args.verbose, final=True)
                        if result.get("status") != "completed":
                            continue
                return 0
            if command == ":status":
                status = session.status()
                print("\nSESSION STATUS\n--------------")
                print(f"Source: {status['source']}")
                print(f"Final output: {status['final_output']}")
                print(f"Approved modifications: {status['approved_modifications']}")
                print(f"Working model structural errors: {status['working_structural_errors']}")
                print(f"Unsaved final BPMN: {'YES' if status['unsaved_final_bpmn'] else 'NO'}")
                print(f"Active process: {status['active_process_id'] or 'not established'}")
            elif command == ":history":
                print("\nSESSION HISTORY\n---------------")
                for index, result in enumerate(session.history, 1):
                    operations = (result.get("plan_summary") or {}).get("planned_operations") or []
                    summary = ", ".join(str(op.get("operation")) for op in operations)
                    print(f"{index}. {summary or result.get('request')}")
                if not session.history:
                    print("No approved modifications.")
            elif command == ":reset":
                session.reset()
                print("Session reset to the untouched source BPMN.")
            elif command == ":finish":
                result = session.finish(force=args.force, overwrite_handler=_confirm_overwrite)
                _print_result(result, args.verbose, final=True)
                if result.get("status") == "completed":
                    return 0
            elif command.startswith(":"):
                print("Commands: :status, :history, :reset, :finish, :quit")
            else:
                result = session.apply(
                    command,
                    clarification_handler=_clarification_prompt,
                    approval_handler=_approve,
                )
                _print_result(result, args.verbose)
    finally:
        session.close()


def _validate(args: argparse.Namespace) -> int:
    result = BasicValidator(BpmnDocument(args.file)).validate()
    _print_json(result)
    return 0 if result["valid_for_agentic_editing"] else 1


def _analyze(args: argparse.Namespace) -> int:
    from bpmn_agentic_engineer.analysis import BpmnAnalyzer

    result = BpmnAnalyzer().analyze(args.file)
    payload = result.to_dict()
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.json_output:
        _print_json(payload)
        return 0
    print("BPMN PROCESS ANALYSIS\n=====================")
    print(f"Process: {result.process_name or Path(result.source_path).stem}")
    for label, key in (
        ("Flow nodes", "total_flow_nodes"),
        ("Sequence flows", "sequence_flows"),
        ("Tasks", "tasks"),
        ("Gateways", "gateways"),
        ("Lanes", "lanes"),
    ):
        print(f"{label}: {result.metrics[key]}")
    print(f"Structural findings: {len(result.findings)}")
    print(f"Structural errors: {result.validation_summary['error_count']}")
    return 0


def _recommend(args: argparse.Namespace) -> int:
    from bpmn_agentic_engineer.recommendation import BpmnRecommendationService

    service = BpmnRecommendationService(
        args.state_dir,
        kernel_ref=args.kaggle_kernel_ref,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        progress_handler=None if args.json_output else print,
    )
    result = service.recommend(args.file, goal=args.goal)
    if args.json_output:
        _print_json(result.to_dict())
        return 0
    visible = [
        item
        for item in result.recommendations
        if args.show_low_confidence or item.confidence != "low"
    ]
    print("\nBPMN OPTIMIZATION RECOMMENDATIONS\n=================================")
    print(f"Process: {result.process_name or Path(result.source_file).stem}")
    print(f"{len(visible)} recommendations found.")
    if not visible:
        print("\nNo sufficiently grounded optimization recommendations were found.")
        return 0
    for index, item in enumerate(visible, 1):
        print(
            f"\n[{index}] {item.category.replace('_', ' ')} · {item.confidence.upper()} CONFIDENCE"
        )
        print("-" * 48)
        print(item.problem)
        print(f"\nRecommendation:\n{item.recommendation}")
        print("\nEvidence:")
        for element in item.affected_elements:
            lane = f" — {element.lane}" if element.lane else ""
            print(f"- {element.name or element.type}{lane}")
        print(
            f"\nCurrent engine: {'✓ Executable' if item.executable_by_current_engine else 'Analysis only'}"
        )
        print(f"Suggested operation: {item.suggested_operation}")
        if item.assumptions:
            print("Assumptions:")
            for assumption in item.assumptions:
                print(f"- {assumption}")
    return 0


def main() -> None:
    _configure_utf8_console()
    args = build_parser().parse_args()
    handlers = {
        "validate": _validate,
        "analyze": _analyze,
        "recommend": _recommend,
        "change": _change,
        "interactive": _interactive,
    }
    try:
        raise SystemExit(handlers[args.command](args))
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        if getattr(args, "verbose", False):
            raise
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
