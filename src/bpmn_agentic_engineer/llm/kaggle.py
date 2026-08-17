from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Sequence

from bpmn_agentic_engineer.bpmn import BpmnDocument

from .context import CompactContextBuilder
from .prompts import build_messages
from .worker import render_qwen3_worker


_KERNEL_REF = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


class KaggleQwenBridge:
    """Prepare, submit and retrieve one Qwen3 interpretation through Kaggle CLI."""

    def __init__(
        self,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.command_runner = command_runner

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
            "run_id": run_id,
            "request_sha256": request_sha256,
            "model_id": "Qwen/Qwen3-8B",
            "messages": build_messages(normalized_request, context.payload),
        }
        (kernel_dir / "worker.py").write_text(
            render_qwen3_worker(payload),
            encoding="utf-8",
        )
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
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "job_dir": str(job_dir),
            "kernel_dir": str(kernel_dir),
            "output_dir": str(output_dir),
            "process_alias_to_id": context.process_alias_to_id,
        }
        (job_dir / "job.json").write_text(
            json.dumps(local_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        completed = self._run(
            [
                "kaggle",
                "kernels",
                "push",
                "-p",
                str(kernel_dir),
                "--accelerator",
                accelerator,
            ]
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
        completed = self._run(["kaggle", "kernels", "status", kernel_ref])
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
            raise RuntimeError(f"The Kaggle kernel failed. {current['raw']}")
        if current["state"] != "complete":
            raise ValueError(
                "The Kaggle kernel is not complete yet. Current status: " + current["raw"]
            )

        output_dir = Path(str(job["output_dir"])).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        kernel_ref = str(job["kernel_ref"])
        self._run(
            [
                "kaggle",
                "kernels",
                "output",
                kernel_ref,
                "-p",
                str(output_dir),
                "--force",
                "--file-pattern",
                r".*llm_(interpretation\.json|raw_output\.txt|job_manifest\.json)$",
            ]
        )
        result_path = output_dir / "llm_interpretation.json"
        if not result_path.exists():
            matches = list(output_dir.rglob("llm_interpretation.json"))
            if matches:
                result_path = matches[0]
        if not result_path.exists():
            raise FileNotFoundError(
                "Kaggle completed but llm_interpretation.json was not downloaded."
            )
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
            raise ValueError("Kaggle interpretation output must be one JSON object.")
        return result

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
            raise ValueError("LLM result must contain one JSON object.")
        return payload

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"

        try:
            return self.command_runner(
                list(command),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Kaggle CLI command failed: {details}") from exc

    @staticmethod
    def _validate_kernel_ref(kernel_ref: str) -> None:
        if not _KERNEL_REF.fullmatch(kernel_ref):
            raise ValueError(
                "kaggle kernel reference must use the form 'owner/kernel-slug'."
            )

    @staticmethod
    def _ensure_cli() -> None:
        if shutil.which("kaggle") is None:
            raise RuntimeError(
                "Kaggle CLI was not found. Install it and authenticate before LLM mode."
            )
