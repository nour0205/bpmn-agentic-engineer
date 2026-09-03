from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bpmn_agentic_engineer.agent import AgentService
from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.validation import BasicValidator

State = dict[str, Any]
ClarificationHandler = Callable[[State], dict[str, Any] | str | None]
ApprovalHandler = Callable[[State], bool]
ProgressHandler = Callable[[str], None]
OverwriteHandler = Callable[[Path], bool]


def default_output_path(source_file: str | Path, output_dir: str | Path | None = None) -> Path:
    """Return one final output path while preserving the source filename exactly."""
    source = Path(source_file).expanduser().resolve()
    directory = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else Path.cwd().resolve() / "generated"
    )
    return directory / source.name


class BpmnChangeService:
    """High-level facade over the durable, approved agent workflow."""

    def __init__(
        self,
        state_dir: str | Path = ".bpmn_agent",
        *,
        agent_service: Any | None = None,
        kernel_ref: str = "nourkouider05/bpmn-qwen3-interpreter",
        poll_interval: float = 10.0,
        timeout: float = 3600.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        progress_handler: ProgressHandler | None = None,
    ):
        self.agent = agent_service or AgentService(state_dir)
        self.kernel_ref = kernel_ref
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.sleep = sleep
        self.clock = clock
        self.progress = progress_handler or (lambda _message: None)

    def start_session(
        self,
        source_file: str | Path,
        output_file: str | Path | None = None,
        *,
        output_dir: str | Path | None = None,
    ) -> BpmnTransformationSession:
        return BpmnTransformationSession(
            source_file,
            self,
            output_file=output_file,
            output_dir=output_dir,
        )

    def run_change(
        self,
        source_file: str | Path,
        request: str,
        output_file: str | Path | None = None,
        clarification_handler: ClarificationHandler | None = None,
        approval_handler: ApprovalHandler | None = None,
        *,
        process_id: str | None = None,
    ) -> State:
        """Execute one approved request to a new file; used atomically by sessions."""
        source = Path(source_file).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"BPMN file not found: {source}")
        if not request or not request.strip():
            raise ValueError("The BPMN change request cannot be empty.")
        output = (
            Path(output_file).expanduser().resolve()
            if output_file is not None
            else default_output_path(source)
        )
        if output == source:
            raise ValueError("The output BPMN must be different from the input BPMN.")
        if output.exists():
            raise FileExistsError(f"Output BPMN already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

        self.progress("Analyzing BPMN...")
        state = self.agent.start(
            source,
            request,
            output_path=output,
            process_id=process_id,
            interpretation_mode="qwen3_kaggle",
            kaggle_kernel_ref=self.kernel_ref,
        )
        run_id = str(state["run_id"])
        deadline = self.clock() + self.timeout
        while True:
            status = state.get("status")
            if status == "waiting_for_llm":
                self.progress("Waiting for Qwen3 interpretation...")
                state = self._wait_for_llm(run_id, deadline)
                continue
            if status == "needs_clarification":
                if clarification_handler is None:
                    return self._result(state, source, output)
                answer = clarification_handler(state)
                if answer is None:
                    state = self.agent.resume(run_id, cancelled=True)
                elif isinstance(answer, str):
                    state = self.agent.resume(run_id, target_query=answer)
                elif isinstance(answer, dict):
                    state = self.agent.resume(run_id, **answer)
                else:
                    raise TypeError("clarification_handler must return a string, dict, or None.")
                continue
            if status == "waiting_for_approval":
                self.progress("Deterministic plan ready for approval.")
                approved = approval_handler(state) if approval_handler is not None else False
                state = self.agent.resume(run_id, approved=bool(approved), output_path=output)
                continue
            if status in {"completed", "cancelled", "failed"}:
                return self._result(state, source, output)
            return self._result(state, source, output)

    def _wait_for_llm(self, run_id: str, deadline: float) -> State:
        while True:
            if self.clock() >= deadline:
                return self._failure(run_id, "Timed out waiting for Kaggle interpretation.")
            try:
                remote = self.agent.llm_status(run_id)
            except Exception as exc:  # noqa: BLE001 - remote integration boundary
                if self.clock() + self.poll_interval >= deadline:
                    return self._failure(run_id, f"Kaggle status failed: {exc}")
                self.progress("Kaggle status unavailable; retrying...")
                self.sleep(self.poll_interval)
                continue
            remote_state = str(remote.get("state", "unknown")).casefold()
            if remote_state == "complete":
                self.progress("Interpretation received. Building deterministic plan...")
                try:
                    return self.agent.resume(run_id, fetch_llm=True)
                except Exception as exc:  # noqa: BLE001 - remote integration boundary
                    return self._failure(run_id, f"Could not fetch Kaggle result: {exc}")
            if remote_state in {"failed", "error", "cancelled", "canceled"}:
                return self._failure(
                    run_id,
                    f"Kaggle interpretation failed: {remote.get('raw') or remote_state}",
                )
            self.sleep(self.poll_interval)

    def _failure(self, run_id: str, message: str) -> State:
        try:
            state = self.agent.status(run_id)
        except Exception:  # noqa: BLE001 - preserve the original remote failure
            state = {"run_id": run_id}
        return {**state, "status": "failed", "error": message}

    @staticmethod
    def _result(state: State, source: Path, output: Path) -> State:
        execution = state.get("execution_result") or {}
        plan = state.get("plan") or {}
        return {
            "status": state.get("status"),
            "source_file": str(source),
            "output_file": execution.get("output_file") or (str(output) if output.exists() else None),
            "interpretation": state.get("llm_interpretation"),
            "plan_summary": {
                "status": plan.get("status"),
                "selected_target": plan.get("selected_target"),
                "planned_operations": plan.get("planned_operations", []),
                "clarification_questions": plan.get("clarification_questions", []),
                "candidate_matches": plan.get("candidate_matches", []),
            },
            "execution_diff": execution.get("diff"),
            "validation": state.get("validation"),
            "error": state.get("error"),
            "debug": {"run_id": state.get("run_id")},
        }


class BpmnTransformationSession:
    """One source, many atomic approved changes, and one final public BPMN."""

    def __init__(
        self,
        source_file: str | Path,
        service: BpmnChangeService,
        output_file: str | Path | None = None,
        output_dir: str | Path | None = None,
    ):
        self.original = Path(source_file).expanduser().resolve()
        if not self.original.exists():
            raise FileNotFoundError(f"BPMN file not found: {self.original}")
        self.final_output = (
            Path(output_file).expanduser().resolve()
            if output_file is not None
            else default_output_path(self.original, output_dir)
        )
        if self.final_output == self.original:
            raise ValueError("The final BPMN must be different from the source BPMN.")
        self.service = service
        self._temporary = tempfile.TemporaryDirectory(prefix="bpmn_working_")
        self._working_root = Path(self._temporary.name)
        self.current = self.original
        self.history: list[State] = []
        self.attempts: list[State] = []
        self.active_process_id: str | None = None
        self.unsaved = False
        self.validation = BasicValidator(BpmnDocument(self.original)).validate()

    def apply(
        self,
        request: str,
        *,
        clarification_handler: ClarificationHandler | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> State:
        next_working = self._working_root / f"working_{len(self.attempts) + 1:04d}.bpmn"
        try:
            result = self.service.run_change(
                self.current,
                request,
                output_file=next_working,
                clarification_handler=clarification_handler,
                approval_handler=approval_handler,
                process_id=self.active_process_id,
            )
        except Exception as exc:  # noqa: BLE001 - one failed recommendation must roll back
            result = {"status": "failed", "error": str(exc), "request": request}
        result["request"] = request
        result["working_model_updated"] = False
        self.attempts.append(result)
        if result.get("status") != "completed" or not next_working.exists():
            if next_working.exists():
                next_working.unlink()
            return result
        validation = BasicValidator(BpmnDocument(next_working)).validate()
        if not validation["valid_for_agentic_editing"] or validation["error_count"]:
            next_working.unlink(missing_ok=True)
            result.update(
                status="failed",
                error="The recommendation was rolled back because validation failed.",
                validation=validation,
                output_file=None,
            )
            return result
        selected = (result.get("plan_summary") or {}).get("selected_target") or {}
        selected_process = selected.get("process_id")
        if self.active_process_id and selected_process and selected_process != self.active_process_id:
            next_working.unlink(missing_ok=True)
            result.update(
                status="failed",
                error="The recommendation attempted to switch the active process scope.",
                output_file=None,
            )
            return result
        previous = self.current
        self.current = next_working
        if previous != self.original and previous.parent == self._working_root:
            previous.unlink(missing_ok=True)
            previous.with_suffix(previous.suffix + ".metadata.json").unlink(missing_ok=True)
        self.active_process_id = self.active_process_id or selected_process
        self.validation = validation
        self.unsaved = True
        result.update(
            output_file=None,
            validation=validation,
            working_model_updated=True,
            session_changes=len(self.history) + 1,
            active_process_id=self.active_process_id,
        )
        self.history.append(result)
        return result

    def finish(
        self,
        *,
        force: bool = False,
        overwrite_handler: OverwriteHandler | None = None,
    ) -> State:
        validation = BasicValidator(BpmnDocument(self.current)).validate()
        if not validation["valid_for_agentic_editing"] or validation["error_count"]:
            return {
                "status": "failed",
                "error": "Final validation failed; no final BPMN was written.",
                "validation": validation,
                "output_file": None,
            }
        if (
            self.final_output.exists()
            and not force
            and (overwrite_handler is None or not overwrite_handler(self.final_output))
        ):
            return {
                "status": "collision",
                "error": f"Final output already exists: {self.final_output}",
                "validation": validation,
                "output_file": None,
            }
        self.final_output.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = self.final_output.with_name(f".{self.final_output.name}.tmp")
        shutil.copy2(self.current, temporary_output)
        temporary_output.replace(self.final_output)
        self.unsaved = False
        return {
            "status": "completed",
            "source_file": str(self.original),
            "output_file": str(self.final_output),
            "approved_modifications": len(self.history),
            "validation": validation,
            "active_process_id": self.active_process_id,
        }

    def reset(self) -> None:
        for path in self._working_root.glob("working_*.bpmn*"):
            path.unlink(missing_ok=True)
        self.current = self.original
        self.history.clear()
        self.attempts.clear()
        self.active_process_id = None
        self.unsaved = False
        self.validation = BasicValidator(BpmnDocument(self.original)).validate()

    def status(self) -> State:
        return {
            "source": str(self.original),
            "final_output": str(self.final_output),
            "approved_modifications": len(self.history),
            "working_structural_errors": self.validation["error_count"],
            "unsaved_final_bpmn": self.unsaved,
            "active_process_id": self.active_process_id,
        }

    def close(self) -> None:
        self._temporary.cleanup()


BpmnInteractiveSession = BpmnTransformationSession
