from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.execution import BpmnPlanExecutor
from bpmn_agentic_engineer.integrity import verify_plan_checksum
from bpmn_agentic_engineer.llm import InterpretationValidator, KaggleQwenBridge
from bpmn_agentic_engineer.planning import ChangePlanner
from bpmn_agentic_engineer.validation import BasicValidator

from .state import AgentState, history_event


class AgentNodes:
    """Deterministic nodes used by the BPMN orchestration graph."""

    def inspect_source(self, state: AgentState) -> dict[str, Any]:
        try:
            document = BpmnDocument(state["file_path"])
            inspector = ProcessInspector(document)
            validation = BasicValidator(document).validate()
            status = "inspecting" if validation["valid_for_agentic_editing"] else "failed"
            error = None
            message = "Source BPMN inspected and baseline validation completed."
            if status == "failed":
                error = "The source BPMN has blocking validation errors."
                message = error

            return {
                "status": status,
                "inspection": inspector.summary(include_elements=False),
                "baseline_validation": validation,
                "error": error,
                "history": [history_event("inspect", status, message)],
            }
        except Exception as exc:  # deterministic boundary for graph state
            return {
                "status": "failed",
                "error": str(exc),
                "history": [history_event("inspect", "failed", str(exc))],
            }


    def submit_llm(self, state: AgentState) -> dict[str, Any]:
        try:
            kernel_ref = state.get("kaggle_kernel_ref")
            if not kernel_ref:
                raise ValueError(
                    "qwen3_kaggle mode requires kaggle_kernel_ref='owner/kernel-slug'."
                )
            bridge = KaggleQwenBridge()
            job = bridge.submit(
                run_id=state["run_id"],
                file_path=state["file_path"],
                request_text=state["request_text"],
                job_root=state["llm_job_root"],
                kernel_ref=kernel_ref,
                accelerator=state.get("kaggle_accelerator", "NvidiaTeslaT4"),
            )
            return {
                "status": "waiting_for_llm",
                "llm_job": job,
                "llm_error": None,
                "history": [
                    history_event(
                        "llm_submit",
                        "waiting_for_llm",
                        "The Qwen3-8B Kaggle job was submitted and the workflow paused.",
                    )
                ],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "llm_error": str(exc),
                "error": str(exc),
                "history": [history_event("llm_submit", "failed", str(exc))],
            }

    def llm_gate(self, state: AgentState) -> dict[str, Any]:
        response = interrupt(
            {
                "kind": "llm_wait",
                "run_id": state["run_id"],
                "status": "waiting_for_llm",
                "model": "Qwen/Qwen3-8B",
                "job": state.get("llm_job", {}),
                "instruction": (
                    "Resume with --fetch-llm after the Kaggle run completes, or provide "
                    "--llm-result-file for a previously downloaded interpretation."
                ),
            }
        )
        if not isinstance(response, dict):
            raise ValueError("LLM resume payload must be a JSON object.")
        if response.get("cancelled"):
            return {
                "status": "cancelled",
                "error": None,
                "history": [history_event("llm", "cancelled", "The run was cancelled.")],
            }
        raw_interpretation = response.get("interpretation")
        if not isinstance(raw_interpretation, dict):
            raise ValueError("The resume payload must contain an interpretation object.")

        document = BpmnDocument(state["file_path"])
        validated = InterpretationValidator().validate(document, raw_interpretation)
        hints = validated["planner_hints"]
        interpretation = validated["interpretation"]
        message = "Qwen3 interpretation validated; deterministic planning will now begin."
        if interpretation.get("requires_clarification"):
            message = (
                "Qwen3 identified missing or ambiguous information; the deterministic planner "
                "will verify and ask for clarification."
            )
        return {
            "operation": state.get("operation") or hints.get("operation"),
            "target_query": state.get("target_query") or hints.get("target_query"),
            "source_queries": state.get("source_queries") or hints.get("source_queries") or [],
            "process_id": state.get("process_id") or hints.get("process_id"),
            "new_name": state.get("new_name") or hints.get("new_name"),
            "new_bpmn_type": state.get("new_bpmn_type") or hints.get("new_bpmn_type"),
            "lane_name": state.get("lane_name") or hints.get("lane_name"),
            "llm_interpretation": interpretation,
            "llm_error": None,
            "status": "interpreted",
            "error": None,
            "history": [history_event("llm", "interpreted", message)],
        }

    def plan_change(self, state: AgentState) -> dict[str, Any]:
        try:
            document = BpmnDocument(state["file_path"])
            inspector = ProcessInspector(document)
            plan = ChangePlanner(document, inspector).plan(
                state["request_text"],
                operation=state.get("operation"),
                target_element_id=state.get("target_element_id"),
                target_query=state.get("target_query"),
                process_id=state.get("process_id"),
                new_name=state.get("new_name"),
                lane_name=state.get("lane_name"),
                source_queries=state.get("source_queries"),
                new_bpmn_type=state.get("new_bpmn_type"),
            )

            if plan.get("status") == "ready_for_approval":
                status = "waiting_for_approval"
                message = "A checksummed deterministic plan is ready for human approval."
            elif plan.get("requires_clarification"):
                status = "needs_clarification"
                message = "The target or requested operation requires clarification."
            else:
                status = "failed"
                message = f"Planning stopped with status {plan.get('status')!r}."

            return {
                "status": status,
                "plan": plan,
                "approved": None,
                "approved_plan_checksum": None,
                "execution_result": {},
                "final_validation": {},
                "error": None if status != "failed" else message,
                "history": [history_event("plan", status, message)],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "history": [history_event("plan", "failed", str(exc))],
            }

    def clarification_gate(self, state: AgentState) -> dict[str, Any]:
        plan = state.get("plan") or {}
        response = interrupt(
            {
                "kind": "clarification",
                "run_id": state["run_id"],
                "status": "needs_clarification",
                "questions": plan.get("clarification_questions", []),
                "candidate_matches": plan.get("candidate_matches", []),
                "accepted_fields": [
                    "target_element_id",
                    "target_query",
                    "source_queries",
                    "process_id",
                    "new_name",
                    "new_bpmn_type",
                    "lane_name",
                    "output_path",
                    "cancelled",
                ],
            }
        )

        if not isinstance(response, dict):
            raise ValueError("Clarification response must be a JSON object.")
        if response.get("cancelled"):
            return {
                "status": "cancelled",
                "error": None,
                "history": [
                    history_event("clarification", "cancelled", "The run was cancelled.")
                ],
            }

        allowed = {
            "target_element_id",
            "target_query",
            "source_queries",
            "process_id",
            "new_name",
            "new_bpmn_type",
            "lane_name",
            "output_path",
        }
        updates = {
            key: response[key]
            for key in allowed
            if key in response and response[key] is not None
        }
        if not updates:
            raise ValueError("Clarification did not provide any usable field.")

        return {
            **updates,
            "status": "received",
            "plan": {},
            "approved": None,
            "approved_plan_checksum": None,
            "error": None,
            "history": [
                history_event(
                    "clarification",
                    "received",
                    "Clarification recorded; the source and plan will be recomputed.",
                )
            ],
        }

    def approval_gate(self, state: AgentState) -> dict[str, Any]:
        plan = state.get("plan") or {}
        response = interrupt(
            {
                "kind": "approval",
                "run_id": state["run_id"],
                "status": "waiting_for_approval",
                "plan_checksum": plan.get("plan_checksum"),
                "source_sha256": plan.get("source_sha256"),
                "selected_target": plan.get("selected_target"),
                "planned_operations": plan.get("planned_operations", []),
                "risks": plan.get("risks", []),
                "assumptions": plan.get("assumptions", []),
                "acceptance_criteria": plan.get("acceptance_criteria", []),
                "output_path": state.get("output_path"),
                "instruction": (
                    "Approve or reject this exact checksummed plan. "
                    "An output path is required before execution."
                ),
            }
        )

        if isinstance(response, bool):
            response = {"approved": response}
        if not isinstance(response, dict):
            raise ValueError("Approval response must be a boolean or JSON object.")

        if response.get("cancelled") or response.get("approved") is False:
            return {
                "approved": False,
                "status": "cancelled",
                "error": None,
                "history": [
                    history_event("approval", "cancelled", "The proposed plan was rejected.")
                ],
            }
        if response.get("approved") is not True:
            raise ValueError("Approval response must explicitly set approved=true or false.")

        output_path = response.get("output_path") or state.get("output_path")
        if not output_path:
            raise ValueError("An output_path is required before approving execution.")
        if not verify_plan_checksum(plan):
            raise ValueError("The persisted plan checksum is invalid.")

        return {
            "approved": True,
            "approved_plan_checksum": plan.get("plan_checksum"),
            "output_path": str(Path(str(output_path)).expanduser().resolve()),
            "status": "executing",
            "error": None,
            "history": [
                history_event(
                    "approval",
                    "executing",
                    "The exact persisted plan was approved for execution on a copy.",
                )
            ],
        }

    def execute_plan(self, state: AgentState) -> dict[str, Any]:
        try:
            plan = state.get("plan") or {}
            if not state.get("approved"):
                raise ValueError("The plan has not been approved.")
            if plan.get("plan_checksum") != state.get("approved_plan_checksum"):
                raise ValueError("The approved plan checksum no longer matches persisted state.")
            if not verify_plan_checksum(plan):
                raise ValueError("The persisted plan checksum is invalid.")
            output_path = state.get("output_path")
            if not output_path:
                raise ValueError("No output path was provided.")

            result = BpmnPlanExecutor().execute(plan, output_path, approved=True)
            if result.get("status") == "execution_succeeded":
                status = "validating"
                error = None
                message = "Execution succeeded; the generated BPMN will be independently validated."
            else:
                status = "failed"
                error = result.get("reason") or "Execution was rolled back."
                message = error

            return {
                "status": status,
                "execution_result": result,
                "error": error,
                "history": [history_event("execute", status, message)],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "history": [history_event("execute", "failed", str(exc))],
            }

    def validate_output(self, state: AgentState) -> dict[str, Any]:
        try:
            execution = state.get("execution_result") or {}
            output_path = execution.get("output_file") or state.get("output_path")
            if not output_path:
                raise ValueError("Execution did not produce an output file.")

            validation = BasicValidator(BpmnDocument(output_path)).validate()
            if validation["valid_for_agentic_editing"]:
                return {
                    "status": "completed",
                    "final_validation": validation,
                    "error": None,
                    "history": [
                        history_event(
                            "validate",
                            "completed",
                            "The generated BPMN passed independent structural validation.",
                        )
                    ],
                }

            return {
                "status": "repairing",
                "final_validation": validation,
                "error": "The generated BPMN failed independent validation.",
                "history": [
                    history_event(
                        "validate",
                        "repairing",
                        "Validation failed; the workflow entered the repair boundary.",
                    )
                ],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "history": [history_event("validate", "failed", str(exc))],
            }

    def repair_boundary(self, state: AgentState) -> dict[str, Any]:
        attempts = int(state.get("repair_attempts", 0)) + 1
        message = (
            "Automatic repair strategies are intentionally disabled in Milestone 4. "
            "The failed validation result has been preserved for Milestone 5."
        )
        return {
            "status": "failed",
            "repair_attempts": attempts,
            "error": message,
            "history": [history_event("repair", "failed", message)],
        }
