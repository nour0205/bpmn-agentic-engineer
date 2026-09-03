from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence


def run_kaggle(
    args: Sequence[str],
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = 120.0,
    max_attempts: int = 3,
    retry_delay: float = 2.0,
) -> subprocess.CompletedProcess[str]:
    """Run Kaggle through the active Python interpreter with a UTF-8 contract."""
    environment = os.environ.copy()
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    command = [sys.executable, "-X", "utf8", "-m", "kaggle", *args]
    for attempt in range(1, max_attempts + 1):
        try:
            return command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            if attempt == max_attempts:
                raise RuntimeError(f"Kaggle CLI timed out after {timeout:g} seconds.") from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            transient = any(
                marker in details.casefold()
                for marker in (
                    "failed to resolve",
                    "name resolution",
                    "connection reset",
                    "connection aborted",
                    "max retries exceeded",
                    "timed out",
                    "temporarily unavailable",
                )
            )
            if not transient or attempt == max_attempts:
                raise RuntimeError(f"Kaggle CLI command failed: {details}") from exc
        time.sleep(retry_delay * attempt)
    raise AssertionError("unreachable")
