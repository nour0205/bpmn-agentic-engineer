from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bpmn_agentic_engineer.llm.kaggle import KaggleQwenBridge
from bpmn_agentic_engineer.llm.kaggle_command import run_kaggle
from bpmn_agentic_engineer.llm.worker import render_qwen3_worker
from bpmn_agentic_engineer.recommendation.kaggle import RecommendationKaggleBridge
from bpmn_agentic_engineer.recommendation.prompts import SYSTEM_PROMPT

FRENCH = (
    "Détermination des besoins d'approvisionnement · Direction d'Approvisionnement · "
    "Génération automatique · Effectuer une analyse financière"
)


def test_kaggle_wrapper_forces_utf8_and_preserves_unicode_streams() -> None:
    captured = {}

    def runner(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=FRENCH, stderr="échec évité")

    result = run_kaggle(["kernels", "status", "owner/kernel"], command_runner=runner)
    assert captured["command"][:5] == [sys.executable, "-X", "utf8", "-m", "kaggle"]
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"
    assert captured["kwargs"]["env"]["PYTHONUTF8"] == "1"
    assert result.stdout == FRENCH
    assert result.stderr == "échec évité"


def test_kaggle_wrapper_retries_transient_dns_failure() -> None:
    attempts = 0

    def runner(command, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise subprocess.CalledProcessError(
                1,
                command,
                stderr="Max retries exceeded: failed to resolve api.kaggle.com",
            )
        return subprocess.CompletedProcess(command, 0, stdout="complete", stderr="")

    result = run_kaggle(
        ["kernels", "status", "owner/kernel"],
        command_runner=runner,
        retry_delay=0,
    )
    assert attempts == 3
    assert result.stdout == "complete"


def test_change_and_recommendation_manifests_have_explicit_job_contracts(tmp_path: Path) -> None:
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    change = KaggleQwenBridge(command_runner=runner)
    change_job = change.submit(
        run_id="change_unicode",
        file_path=Path("tests/fixtures/execution_process.bpmn"),
        request_text=f"Renommer {FRENCH}",
        job_root=tmp_path / "change",
        kernel_ref="owner/kernel",
    )
    recommendation = RecommendationKaggleBridge(command_runner=runner)
    rec_job = recommendation.submit_context(
        run_id="recommend_unicode",
        context={"source": {"filename": f"{FRENCH}.bpmn"}, "findings": []},
        job_root=tmp_path / "recommend",
        kernel_ref="owner/kernel",
    )
    assert change_job["job_type"] == "interpret_change"
    assert change_job["result_filename"] == "llm_interpretation.json"
    assert rec_job["job_type"] == "recommend_optimizations"
    assert rec_job["result_filename"] == "recommendation_result.json"
    manifest_text = (Path(rec_job["job_dir"]) / "job.json").read_text(encoding="utf-8")
    worker_text = (Path(rec_job["kernel_dir"]) / "worker.py").read_text(encoding="utf-8")
    assert "recommend_optimizations" in manifest_text
    namespace = {"__name__": "staging_test"}
    exec(compile(worker_text, "worker.py", "exec"), namespace)  # noqa: S102
    assert FRENCH in namespace["PAYLOAD"]["messages"][1]["content"]
    assert all(
        command[:5] == [sys.executable, "-X", "utf8", "-m", "kaggle"] for command in commands
    )


def test_shared_worker_dispatches_both_job_types() -> None:
    for job_type, filename in (
        ("interpret_change", "llm_interpretation.json"),
        ("recommend_optimizations", "recommendation_result.json"),
    ):
        source = render_qwen3_worker(
            {
                "schema_version": "1.0",
                "job_type": job_type,
                "result_filename": filename,
                "run_id": "run",
                "request_sha256": "hash",
                "messages": [{"role": "user", "content": FRENCH}],
            }
        )
        compile(source, "worker.py", "exec")
        assert f'"{job_type}"' in source
        assert filename in source
        assert "job_error.json" in source


def test_remote_error_artifact_is_parsed_and_formatted(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    diagnostic = {
        "stage": "model_load",
        "error_type": "RuntimeError",
        "message": "Échec du chargement Qwen",
        "traceback_tail": ["safe traceback"],
    }
    (output / "job_error.json").write_text(
        json.dumps(diagnostic, ensure_ascii=False), encoding="utf-8"
    )
    bridge = KaggleQwenBridge()
    bridge._download_outputs = lambda job: None
    parsed = bridge.fetch_error({"output_dir": str(output)})
    assert parsed == diagnostic
    assert bridge.format_failure({"raw": "ERROR"}, parsed) == (
        "Qwen job failed during model_load: Échec du chargement Qwen"
    )


def test_recommendation_success_artifact_is_exactly_selected(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = {"recommendations": []}
    (output / "recommendation_result.json").write_text(json.dumps(result), encoding="utf-8")
    (output / "llm_job_manifest.json").write_text(
        json.dumps({"run_id": "rec", "request_sha256": "hash"}), encoding="utf-8"
    )
    bridge = KaggleQwenBridge()
    bridge.status = lambda job: {"state": "complete"}
    bridge._download_outputs = lambda job: None
    job = {
        "run_id": "rec",
        "request_sha256": "hash",
        "result_filename": "recommendation_result.json",
        "output_dir": str(output),
        "kernel_ref": "owner/kernel",
    }
    assert bridge.fetch(job) == result


def test_recommendation_prompt_bounds_remote_output() -> None:
    assert "at most 3 recommendations" in SYSTEM_PROMPT
    assert "only existing elements that the proposed change directly modifies" in SYSTEM_PROMPT
