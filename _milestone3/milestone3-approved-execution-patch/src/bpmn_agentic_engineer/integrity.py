from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file."""
    file_path = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_plan_payload(plan: dict[str, Any]) -> bytes:
    """Serialize a plan deterministically, excluding its checksum field."""
    payload = deepcopy(plan)
    payload.pop("plan_checksum", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_plan_checksum(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_payload(plan)).hexdigest()


def attach_plan_integrity(
    plan: dict[str, Any],
    source_path: str | Path,
) -> dict[str, Any]:
    """Add source and plan digests to a planner result."""
    payload = deepcopy(plan)
    payload["source_sha256"] = sha256_file(source_path)
    payload["plan_checksum"] = compute_plan_checksum(payload)
    return payload


def verify_plan_checksum(plan: dict[str, Any]) -> bool:
    expected = plan.get("plan_checksum")
    if not isinstance(expected, str) or not expected:
        return False
    return expected == compute_plan_checksum(plan)
