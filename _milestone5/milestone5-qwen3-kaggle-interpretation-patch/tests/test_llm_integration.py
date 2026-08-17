from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.llm import (
    CompactContextBuilder,
    InterpretationValidator,
    KaggleQwenBridge,
    LlmInterpretation,
)
from bpmn_agentic_engineer.llm.worker import render_qwen3_worker
from bpmn_agentic_engineer.planning import ChangePlanner


FIXTURES = Path(__file__).parent / "fixtures"


def test_llm_schema_accepts_id_free_payload() -> None:
    interpretation = LlmInterpretation.from_dict(
        {
            "schema_version": "1.0",
            "operation": "insert_task_before",
            "target_query": "Rédiger le cahier des charges",
            "new_name": "Valider le dossier",
            "lane_name": "SPCM",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 0.93,
        },
        allowed_process_aliases={"process_1"},
    )
    assert interpretation.operation == "insert_task_before"
    assert interpretation.process_alias == "process_1"


def test_llm_schema_rejects_bpmn_ids() -> None:
    with pytest.raises(ValueError, match="not allowed to return BPMN identifiers"):
        LlmInterpretation.from_dict(
            {
                "operation": "rename_element",
                "target_query": "Task",
                "new_name": "New task",
                "process_alias": None,
                "requires_clarification": False,
                "clarification_question": None,
                "confidence": 0.8,
                "process_id": "Process_1",
            }
        )


def test_context_hides_real_identifiers() -> None:
    document = BpmnDocument(FIXTURES / "execution_process.bpmn")
    context = CompactContextBuilder(document).build()
    serialized = json.dumps(context.payload)
    assert "Process_1" not in serialized
    assert "Task_1" not in serialized
    assert context.process_alias_to_id == {"process_1": "Process_1"}
    assert context.payload["processes"][0]["alias"] == "process_1"


def test_interpretation_maps_alias_locally() -> None:
    document = BpmnDocument(FIXTURES / "execution_process.bpmn")
    result = InterpretationValidator().validate(
        document,
        {
            "schema_version": "1.0",
            "operation": "insert_task_before",
            "target_query": "Rédiger le cahier des charges",
            "new_name": "Valider le dossier",
            "lane_name": "SPCM",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 0.9,
        },
    )
    assert result["planner_hints"]["process_id"] == "Process_1"


def test_planner_accepts_explicit_llm_operation() -> None:
    document = BpmnDocument(FIXTURES / "execution_process.bpmn")
    plan = ChangePlanner(document, ProcessInspector(document)).plan(
        "Place une validation dans le flux.",
        operation="insert_task_before",
        target_query="Rédiger le cahier des charges",
        new_name="Valider le dossier",
        process_id="Process_1",
    )
    assert plan["status"] == "ready_for_approval"
    assert plan["request"]["operation"] == "insert_task_before"


def test_rendered_worker_is_valid_python(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        render_qwen3_worker(
            {
                "messages": [
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "Test"},
                ]
            }
        ),
        encoding="utf-8",
    )
    compile(worker.read_text(encoding="utf-8"), str(worker), "exec")


def test_kaggle_bridge_prepares_and_submits_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_runner(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="submitted", stderr="")

    monkeypatch.setattr("bpmn_agentic_engineer.llm.kaggle.shutil.which", lambda _: "kaggle")
    bridge = KaggleQwenBridge(command_runner=fake_runner)
    result = bridge.submit(
        run_id="run_test",
        file_path=FIXTURES / "execution_process.bpmn",
        request_text="Ajoute une validation avant la rédaction du cahier des charges.",
        job_root=tmp_path,
        kernel_ref="owner/bpmn-qwen3-interpreter",
    )

    kernel_dir = Path(result["kernel_dir"])
    assert (kernel_dir / "worker.py").exists()
    assert (kernel_dir / "kernel-metadata.json").exists()
    assert commands[0][:3] == ["kaggle", "kernels", "push"]
    assert "NvidiaTeslaT4" in commands[0]
