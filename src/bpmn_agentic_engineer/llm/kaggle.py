from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument

from .context import CompactContextBuilder
from .kaggle_command import run_kaggle
from .prompts import build_messages
from .worker import render_qwen3_worker

_KERNEL_REF = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


class KaggleQwenBridge:
    """Prepare, submit and retrieve one Qwen3 interpretation through Kaggle CLI."""

    def __init__(
        self,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        command_timeout: float = 120.0,
    ):
        self.command_runner = command_runner
        self.command_timeout = command_timeout

    def submit(
        self,
        *,
        run_id: str,
        file_path: str | Path,
        request_text: str,
        job_root: str | Path,
        kernel_ref: str,
        accelerator: str = "NvidiaTeslaT4",
    ) -> dict[str, Any]:
        self._validate_kernel_ref(kernel_ref)
        self._ensure_cli()

        document = BpmnDocument(file_path)
        context = CompactContextBuilder(document).build()
        job_dir = Path(job_root).expanduser().resolve() / run_id
        kernel_dir = job_dir / "kernel"
        output_dir = job_dir / "output"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        normalized_request = " ".join(request_text.split())
        request_sha256 = hashlib.sha256(normalized_request.encode("utf-8")).hexdigest()
        payload = {
            "schema_version": "1.0",
            "job_type": "interpret_change",
            "result_filename": "llm_interpretation.json",
            "run_id": run_id,
            "request_sha256": request_sha256,
            "model_id": "Qwen/Qwen3-8B",
            "messages": build_messages(normalized_request, context.payload),
        }
        return self._submit_payload(
            run_id=run_id,
            payload=payload,
            request_sha256=request_sha256,
            job_root=job_root,
            kernel_ref=kernel_ref,
            accelerator=accelerator,
            extra_manifest={"process_alias_to_id": context.process_alias_to_id},
        )

    def _submit_payload(
        self,
        *,
        run_id: str,
        payload: dict[str, Any],
        request_sha256: str,
        job_root: str | Path,
        kernel_ref: str,
        accelerator: str,
        extra_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_dir = Path(job_root).expanduser().resolve() / run_id
        kernel_dir = job_dir / "kernel"
        output_dir = job_dir / "output"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        (kernel_dir / "worker.py").write_text(render_qwen3_worker(payload), encoding="utf-8")
        kernel_slug = kernel_ref.split("/", 1)[1]
        kernel_title = re.sub(r"[-_]+", " ", kernel_slug).strip().title()

        metadata = {
            "id": kernel_ref,
            "title": kernel_title,
            "code_file": "worker.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": [],
        }
        (kernel_dir / "kernel-metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        local_manifest = {
            "run_id": run_id,
            "kernel_ref": kernel_ref,
            "accelerator": accelerator,
            "request_sha256": request_sha256,
            "job_type": payload["job_type"],
            "result_filename": payload["result_filename"],
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "job_dir": str(job_dir),
            "kernel_dir": str(kernel_dir),
            "output_dir": str(output_dir),
            **(extra_manifest or {}),
        }
        (job_dir / "job.json").write_text(
            json.dumps(local_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        completed = self._run(
            ["kernels", "push", "-p", str(kernel_dir), "--accelerator", accelerator]
        )
        return {
            **local_manifest,
            "submission_stdout": completed.stdout.strip(),
            "status": "submitted",
        }

    def status(self, job: dict[str, Any]) -> dict[str, Any]:
        self._ensure_cli()
        kernel_ref = str(job.get("kernel_ref", ""))
        self._validate_kernel_ref(kernel_ref)
        completed = self._run(["kernels", "status", kernel_ref])
        text = (completed.stdout + "\n" + completed.stderr).strip()
        normalized = text.casefold()
        if any(word in normalized for word in ("complete", "success")):
            state = "complete"
        elif any(word in normalized for word in ("error", "failed", "cancel")):
            state = "failed"
        elif any(word in normalized for word in ("running", "queued", "pending")):
            state = "running"
        else:
            state = "unknown"
        return {"state": state, "raw": text, "kernel_ref": kernel_ref}

    def fetch(self, job: dict[str, Any]) -> dict[str, Any]:
        current = self.status(job)
        if current["state"] == "failed":
            diagnostic = self.fetch_error(job)
            raise RuntimeError(self.format_failure(current, diagnostic))
        if current["state"] != "complete":
            raise ValueError(
                "The Kaggle kernel is not complete yet. Current status: " + current["raw"]
            )

        output_dir = Path(str(job["output_dir"])).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        result_filename = str(job.get("result_filename") or "llm_interpretation.json")
        self._download_outputs(job)
        result_path = output_dir / result_filename
        if not result_path.exists():
            matches = list(output_dir.rglob(result_filename))
            if matches:
                result_path = matches[0]
        if not result_path.exists():
            raise FileNotFoundError(f"Kaggle completed but {result_filename} was not downloaded.")
        manifest_path = output_dir / "llm_job_manifest.json"
        if not manifest_path.exists():
            matches = list(output_dir.rglob("llm_job_manifest.json"))
            if matches:
                manifest_path = matches[0]
        if not manifest_path.exists():
            raise FileNotFoundError("Kaggle output is missing llm_job_manifest.json.")
        try:
            remote_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Kaggle job manifest JSON: {exc}") from exc
        if remote_manifest.get("run_id") != job.get("run_id"):
            raise ValueError("Downloaded Kaggle output belongs to a different agent run.")
        if remote_manifest.get("request_sha256") != job.get("request_sha256"):
            raise ValueError("Downloaded Kaggle output belongs to a different request.")

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Kaggle interpretation JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise TypeError("Kaggle interpretation output must be one JSON object.")
        return result

    def _download_outputs(self, job: dict[str, Any]) -> None:
        output_dir = Path(str(job["output_dir"])).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        self._run(["kernels", "output", str(job["kernel_ref"]), "-p", str(output_dir), "--force"])

    def fetch_error(self, job: dict[str, Any]) -> dict[str, Any] | None:
        try:
            self._download_outputs(job)
        except RuntimeError:
            return None
        output_dir = Path(str(job["output_dir"])).expanduser().resolve()
        matches = list(output_dir.rglob("job_error.json"))
        if matches:
            try:
                value = json.loads(matches[0].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = None
            if isinstance(value, dict):
                return value
        return self._diagnostic_from_kernel_log(output_dir)

    @staticmethod
    def _diagnostic_from_kernel_log(output_dir: Path) -> dict[str, Any] | None:
        logs = list(output_dir.rglob("*.log"))
        if not logs:
            return None
        try:
            records = json.loads(logs[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(records, list):
            return None
        text = "".join(
            str(record.get("data") or "") for record in records if isinstance(record, dict)
        )
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None
        error_lines = [
            line
            for line in lines
            if "Error:" in line or "Exception:" in line or "Traceback" in line
        ]
        message = error_lines[-1] if error_lines else lines[-1]
        normalized = message.casefold()
        stage = "remote_worker"
        if "outofmemory" in normalized or "cuda out of memory" in normalized:
            stage = "generation"
        elif "pip" in normalized or "module" in normalized:
            stage = "dependency_setup"
        return {
            "stage": stage,
            "error_type": message.split(":", 1)[0],
            "message": message,
            "traceback_tail": lines[-20:],
        }

    @staticmethod
    def format_failure(status: dict[str, Any], diagnostic: dict[str, Any] | None) -> str:
        if diagnostic:
            stage = diagnostic.get("stage") or "unknown"
            message = diagnostic.get("message") or diagnostic.get("error_type") or "unknown error"
            return f"Qwen job failed during {stage}: {message}"
        return f"The Kaggle kernel failed without a diagnostic artifact. {status.get('raw', '')}".strip()

    @staticmethod
    def load_result(path: str | Path) -> dict[str, Any]:
        result_path = Path(path).expanduser().resolve()
        if not result_path.exists():
            raise FileNotFoundError(f"LLM result file not found: {result_path}")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid LLM result JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise TypeError("LLM result must contain one JSON object.")
        return payload

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        args = list(command)
        if args and args[0] == "kaggle":
            args = args[1:]
        return run_kaggle(
            args,
            command_runner=self.command_runner,
            timeout=self.command_timeout,
        )

    @staticmethod
    def _validate_kernel_ref(kernel_ref: str) -> None:
        if not _KERNEL_REF.fullmatch(kernel_ref):
            raise ValueError("kaggle kernel reference must use the form 'owner/kernel-slug'.")

    @staticmethod
    def _ensure_cli() -> None:
        if importlib.util.find_spec("kaggle") is None:
            raise RuntimeError(
                "Kaggle CLI was not found. Install it and authenticate before LLM mode."
            )
