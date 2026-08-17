from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable

from bpmn_agentic_engineer.agent import AgentService


State = dict[str, Any]
ClarificationHandler = Callable[[State], dict[str, Any] | str | None]
ApprovalHandler = Callable[[State], bool]
ProgressHandler = Callable[[str], None]


class BpmnVersionManager:
    def __init__(self, original_file: str | Path, output_dir: str | Path | None = None):
        self.original = Path(original_file).expanduser().resolve()
        self.output_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else self.original.parent / "generated"
        )

    def next_path(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        version = 1
        while True:
            candidate = self.output_dir / f"{self.original.stem}_v{version:03d}.bpmn"
            if not candidate.exists():
                return candidate
            version += 1


class BpmnChangeService:
    """High-level facade over the existing durable agent workflow."""

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

    def run_change(
        self,
        source_file: str | Path,
        request: str,
        output_file: str | Path | None = None,
        clarification_handler: ClarificationHandler | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> State:
        source = Path(source_file).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"BPMN file not found: {source}")
        if not request or not request.strip():
            raise ValueError("The BPMN change request cannot be empty.")
        output = (
            Path(output_file).expanduser().resolve()
            if output_file is not None
            else BpmnVersionManager(source).next_path()
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
                result = self._result(state, source, output)
                if status == "completed":
                    self._write_metadata(result, request)
                return result
            return self._result(state, source, output)

    def _wait_for_llm(self, run_id: str, deadline: float) -> State:
        while True:
            if self.clock() >= deadline:
                return self._failure(run_id, "Timed out waiting for Kaggle interpretation.")
            try:
                remote = self.agent.llm_status(run_id)
            except Exception as exc:
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
                except Exception as exc:
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
        except Exception:
            state = {"run_id": run_id}
        return {**state, "status": "failed", "error": message}

    @staticmethod
    def _result(state: State, source: Path, output: Path) -> State:
        execution = state.get("execution_result") or {}
        plan = state.get("plan") or {}
        return {
            "status": state.get("status"),
            "source_file": str(source),
            "output_file": execution.get("output_file") or (
                str(output) if output.exists() else None
            ),
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

    @staticmethod
    def _write_metadata(result: State, request: str) -> None:
        output = result.get("output_file")
        if not output:
            return
        path = Path(output)
        metadata = {
            "source_version": result.get("source_file"),
            "request": " ".join(request.split()),
            "run_id": (result.get("debug") or {}).get("run_id"),
            "resulting_version": str(path),
            "validation_status": (result.get("validation") or {}).get(
                "valid_for_agentic_editing"
            ),
        }
        path.with_suffix(path.suffix + ".metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class BpmnInteractiveSession:
    def __init__(
        self,
        source_file: str | Path,
        service: BpmnChangeService,
        output_dir: str | Path | None = None,
    ):
        self.original = Path(source_file).expanduser().resolve()
        self.current = self.original
        self.service = service
        self.versions = BpmnVersionManager(self.original, output_dir)
        self.history: list[State] = []

    def apply(
        self,
        request: str,
        *,
        clarification_handler: ClarificationHandler | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> State:
        result = self.service.run_change(
            self.current,
            request,
            output_file=self.versions.next_path(),
            clarification_handler=clarification_handler,
            approval_handler=approval_handler,
        )
        if result.get("status") == "completed" and result.get("output_file"):
            self.current = Path(str(result["output_file"])).resolve()
            self.history.append(result)
        return result

    def reset(self) -> None:
        self.current = self.original

    def status(self) -> State:
        return {
            "original": str(self.original),
            "current": str(self.current),
            "successful_changes": len(self.history),
        }
