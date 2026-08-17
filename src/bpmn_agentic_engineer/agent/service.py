from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any, Iterator
import uuid

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from bpmn_agentic_engineer.llm import KaggleQwenBridge

from .graph import build_agent_graph
from .state import AgentState, InterpretationMode, history_event


class AgentService:
    """Start, resume and inspect durable BPMN agent runs."""

    def __init__(self, state_dir: str | Path = ".bpmn_agent"):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.state_dir / "checkpoints.sqlite"
        self.llm_job_root = self.state_dir / "llm_jobs"
        self.llm_job_root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _graph(self) -> Iterator[Any]:
        with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as checkpointer:
            yield build_agent_graph(checkpointer)

    @staticmethod
    def _config(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}

    def start(
        self,
        file_path: str | Path,
        request_text: str,
        *,
        operation: str | None = None,
        target_element_id: str | None = None,
        target_query: str | None = None,
        source_queries: list[str] | None = None,
        process_id: str | None = None,
        new_name: str | None = None,
        new_bpmn_type: str | None = None,
        lane_name: str | None = None,
        output_path: str | Path | None = None,
        interpretation_mode: InterpretationMode = "deterministic",
        kaggle_kernel_ref: str | None = None,
        kaggle_accelerator: str = "NvidiaTeslaT4",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        source = Path(file_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"BPMN file not found: {source}")
        if not request_text or not request_text.strip():
            raise ValueError("The agent request cannot be empty.")
        if interpretation_mode not in {"deterministic", "qwen3_kaggle"}:
            raise ValueError(f"Unknown interpretation mode: {interpretation_mode!r}.")
        if interpretation_mode == "qwen3_kaggle" and not kaggle_kernel_ref:
            raise ValueError("qwen3_kaggle mode requires --kaggle-kernel-ref owner/slug.")

        resolved_output = (
            str(Path(output_path).expanduser().resolve()) if output_path is not None else None
        )
        identifier = run_id or f"run_{uuid.uuid4().hex[:16]}"
        config = self._config(identifier)

        with self._graph() as graph:
            existing = graph.get_state(config)
            if existing.values:
                raise ValueError(f"Agent run already exists: {identifier}")

            initial: AgentState = {
                "run_id": identifier,
                "file_path": str(source),
                "request_text": " ".join(request_text.split()),
                "operation": operation,
                "target_element_id": target_element_id,
                "target_query": target_query,
                "source_queries": list(source_queries or []),
                "process_id": process_id,
                "new_name": new_name,
                "new_bpmn_type": new_bpmn_type,
                "lane_name": lane_name,
                "output_path": resolved_output,
                "interpretation_mode": interpretation_mode,
                "kaggle_kernel_ref": kaggle_kernel_ref,
                "kaggle_accelerator": kaggle_accelerator,
                "llm_job_root": str(self.llm_job_root),
                "llm_job": {},
                "llm_interpretation": {},
                "llm_error": None,
                "status": "received",
                "inspection": {},
                "baseline_validation": {},
                "plan": {},
                "approved": None,
                "approved_plan_checksum": None,
                "execution_result": {},
                "final_validation": {},
                "repair_attempts": 0,
                "error": None,
                "history": [
                    history_event("start", "received", "A new BPMN agent run was created.")
                ],
            }
            result = graph.invoke(initial, config=config)
            return self._response(graph, config, result)

    def resume(
        self,
        run_id: str,
        *,
        approved: bool | None = None,
        cancelled: bool = False,
        output_path: str | Path | None = None,
        target_element_id: str | None = None,
        target_query: str | None = None,
        source_queries: list[str] | None = None,
        process_id: str | None = None,
        new_name: str | None = None,
        new_bpmn_type: str | None = None,
        lane_name: str | None = None,
        fetch_llm: bool = False,
        llm_result_file: str | Path | None = None,
    ) -> dict[str, Any]:
        config = self._config(run_id)

        with self._graph() as graph:
            snapshot = graph.get_state(config)
            if not snapshot.values:
                raise KeyError(f"Unknown BPMN agent run: {run_id}")
            state = dict(snapshot.values)
            status = state.get("status")

            if status == "waiting_for_llm":
                if cancelled:
                    payload: dict[str, Any] = {"cancelled": True}
                else:
                    if fetch_llm and llm_result_file is not None:
                        raise ValueError("Use either --fetch-llm or --llm-result-file, not both.")
                    bridge = KaggleQwenBridge()
                    if fetch_llm:
                        interpretation = bridge.fetch(state.get("llm_job") or {})
                    elif llm_result_file is not None:
                        interpretation = bridge.load_result(llm_result_file)
                    else:
                        raise ValueError(
                            "This run is waiting for Qwen3. Use --fetch-llm after Kaggle "
                            "completes, or provide --llm-result-file."
                        )
                    payload = {"interpretation": interpretation, "cancelled": False}

            elif status == "needs_clarification":
                payload = {"cancelled": cancelled}
                values = {
                    "target_element_id": target_element_id,
                    "target_query": target_query,
                    "source_queries": source_queries,
                    "process_id": process_id,
                    "new_name": new_name,
                    "new_bpmn_type": new_bpmn_type,
                    "lane_name": lane_name,
                    "output_path": (
                        str(Path(output_path).expanduser().resolve())
                        if output_path is not None
                        else None
                    ),
                }
                payload.update({key: value for key, value in values.items() if value is not None})
                if not cancelled and len(payload) == 1:
                    raise ValueError(
                        "This run needs clarification. Supply a process ID, element ID, "
                        "target query, source queries, name, BPMN type, lane, or cancel the run."
                    )

            elif status == "waiting_for_approval":
                if approved is None and not cancelled:
                    raise ValueError("This run is waiting for explicit approval or rejection.")
                resolved_output = (
                    str(Path(output_path).expanduser().resolve())
                    if output_path is not None
                    else state.get("output_path")
                )
                if approved is True and not resolved_output:
                    raise ValueError("An output path is required before approval.")
                payload = {
                    "approved": False if cancelled else approved,
                    "cancelled": cancelled,
                    "output_path": resolved_output,
                }
            else:
                raise ValueError(f"Run {run_id!r} cannot be resumed from status {status!r}.")

            result = graph.invoke(Command(resume=payload), config=config)
            return self._response(graph, config, result)

    def status(self, run_id: str) -> dict[str, Any]:
        config = self._config(run_id)
        with self._graph() as graph:
            snapshot = graph.get_state(config)
            if not snapshot.values:
                raise KeyError(f"Unknown BPMN agent run: {run_id}")
            return self._response(graph, config, None)

    def llm_status(self, run_id: str) -> dict[str, Any]:
        config = self._config(run_id)
        with self._graph() as graph:
            snapshot = graph.get_state(config)
            if not snapshot.values:
                raise KeyError(f"Unknown BPMN agent run: {run_id}")
            state = dict(snapshot.values)
            job = state.get("llm_job") or {}
            if not job:
                raise ValueError(f"Run {run_id!r} has no Kaggle LLM job.")
            return KaggleQwenBridge().status(job)

    def _response(
        self,
        graph: Any,
        config: dict[str, dict[str, str]],
        result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        snapshot = graph.get_state(config)
        state = dict(snapshot.values)
        interrupts = self._interrupt_values(result)
        plan = state.get("plan") or {}
        execution = state.get("execution_result") or {}
        return {
            "run_id": state.get("run_id"),
            "status": state.get("status"),
            "file": state.get("file_path"),
            "request": state.get("request_text"),
            "interpretation_mode": state.get("interpretation_mode"),
            "llm_job": state.get("llm_job") or None,
            "llm_interpretation": state.get("llm_interpretation") or None,
            "output_path": state.get("output_path"),
            "next_nodes": list(snapshot.next),
            "interrupt": interrupts[0] if len(interrupts) == 1 else None,
            "interrupts": interrupts,
            "approval_required": state.get("status") == "waiting_for_approval",
            "plan": plan or None,
            "plan_checksum": plan.get("plan_checksum"),
            "selected_target": plan.get("selected_target"),
            "execution_result": execution or None,
            "validation": state.get("final_validation") or None,
            "error": state.get("error"),
            "history": state.get("history", []),
            "state_directory": str(self.state_dir),
        }

    @staticmethod
    def _interrupt_values(result: dict[str, Any] | None) -> list[Any]:
        if not isinstance(result, dict):
            return []
        raw = result.get("__interrupt__", [])
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        return [getattr(item, "value", item) for item in raw]
