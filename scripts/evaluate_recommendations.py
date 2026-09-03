"""Evaluation-only comparison of recommendation JSON against planted dataset issues."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bpmn_agentic_engineer.recommendation import BpmnRecommendationService

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "data" / "bpmn" / "dataset_manifest.json"
CATEGORY_MAP = {
    "manual_sequence": {"AUTOMATION", "SEQUENTIAL_MANUAL_PROCESSING"},
    "redundant_activity": {"REDUNDANCY_REMOVAL", "ACTIVITY_SIMPLIFICATION"},
    "legacy_label": {"LABEL_CLARIFICATION"},
    "missing_control": {"CONTROL_INSERTION"},
}


def evaluate_case(case: dict[str, Any], recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    unmatched = set(range(len(recommendations)))
    detections = 0
    operation_matches = 0
    for issue in case["introduced_issues"]:
        expected_ids = set(issue.get("as_is_elements") or [])
        expected_anchor = issue.get("restore_anchor")
        best = None
        for index in unmatched:
            recommendation = recommendations[index]
            if recommendation.get("category") not in CATEGORY_MAP[issue["category"]]:
                continue
            actual_ids = {
                element.get("element_id")
                for element in recommendation.get("affected_elements", [])
                if element.get("element_id")
            }
            anchors = {
                change.get("anchor_element_id")
                for change in recommendation.get("proposed_changes", [])
                if change.get("anchor_element_id")
            }
            target_match = (
                bool(expected_ids & actual_ids) if expected_ids else expected_anchor in anchors
            )
            if target_match:
                best = index
                break
        if best is not None:
            detections += 1
            recommendation = recommendations[best]
            operation_matches += (
                recommendation.get("suggested_operation") == issue["expected_operation"]
            )
            unmatched.remove(best)
    planted = len(case["introduced_issues"])
    return {
        "case_id": case["case_id"],
        "process": case["process_name"],
        "planted_issues": planted,
        "recommendations": len(recommendations),
        "correct_detections": detections,
        "false_positives": len(unmatched),
        "missed_issues": planted - detections,
        "operation_matches": operation_matches,
    }


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    planted = sum(item["planted_issues"] for item in cases)
    generated = sum(item["recommendations"] for item in cases)
    detected = sum(item["correct_detections"] for item in cases)
    operation_matches = sum(item["operation_matches"] for item in cases)
    return {
        "cases": cases,
        "global": {
            "issue_recall": detected / planted if planted else 0.0,
            "recommendation_precision": detected / generated if generated else 0.0,
            "operation_accuracy": operation_matches / detected if detected else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default=".bpmn_agent/recommendation_evaluation")
    parser.add_argument("--kernel-ref", default="nourkouider05/bpmn-qwen3-interpreter")
    parser.add_argument(
        "--force", action="store_true", help="Regenerate cached recommendation JSON."
    )
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    service = BpmnRecommendationService(kernel_ref=args.kernel_ref)
    reports = []
    for case in manifest["cases"]:
        cached = results_dir / f"{case['case_id']}.json"
        if cached.exists() and not args.force:
            result = json.loads(cached.read_text(encoding="utf-8"))
        else:
            result = service.recommend(ROOT / case["as_is"]).to_dict()
            cached.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        reports.append(evaluate_case(case, result["recommendations"]))
    report = aggregate(reports)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
