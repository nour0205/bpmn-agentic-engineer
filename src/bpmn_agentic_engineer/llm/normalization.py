from __future__ import annotations

import re
import unicodedata
from typing import Any


_GENERIC_TARGET = re.compile(
    r"\b(?:activite|tache)\s+"
    r"(?:liee?\s+a|concernant|relative?\s+a)\s+"
    r"(?P<subject>.+?)"
    r"(?=\s+(?:en|to)\s+|[.!?;]|$)",
    flags=re.IGNORECASE,
)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^\w]+", " ", without_accents.casefold()).split())


def explicit_catalogue_scope(
    request_text: str,
    catalogue: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return only lane/process scope explicitly present in the user's request."""

    request = normalize_text(request_text)
    lane_matches: set[tuple[str, str | None]] = set()
    process_matches: set[str] = set()
    for process in catalogue.get("processes", []):
        if not isinstance(process, dict):
            continue
        alias = process.get("alias")
        participant = process.get("participant_name")
        if (
            isinstance(alias, str)
            and isinstance(participant, str)
            and normalize_text(participant) in request
        ):
            process_matches.add(alias)
        for lane in process.get("lanes", []):
            if not isinstance(lane, dict):
                continue
            lane_name = lane.get("name")
            if not isinstance(lane_name, str) or not lane_name.strip():
                continue
            if normalize_text(lane_name) in request:
                lane_matches.add((lane_name.strip(), alias if isinstance(alias, str) else None))

    if len(lane_matches) == 1:
        lane_name, alias = next(iter(lane_matches))
        return lane_name, alias
    if len(process_matches) == 1:
        return None, next(iter(process_matches))
    return None, None


def _generic_subject(request_text: str) -> str | None:
    normalized = normalize_text(request_text)
    match = _GENERIC_TARGET.search(normalized)
    if match is None:
        return None
    subject = re.sub(r"^(?:la|le|les|l|une|un)\s+", "", match.group("subject")).strip()
    return subject or None


def _catalogue_candidates(
    catalogue: dict[str, Any],
    subject: str,
    process_alias: str | None,
) -> set[tuple[str, str | None, str | None]]:
    subject_tokens = set(subject.split())
    candidates: set[tuple[str, str | None, str | None]] = set()
    for process in catalogue.get("processes", []):
        if not isinstance(process, dict):
            continue
        alias = process.get("alias")
        if process_alias and alias != process_alias:
            continue
        for element in process.get("elements", []):
            if not isinstance(element, dict):
                continue
            element_type = element.get("type")
            if not isinstance(element_type, str) or "task" not in element_type.casefold():
                continue
            name = element.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            normalized_name = normalize_text(name)
            name_tokens = set(normalized_name.split())
            if subject in normalized_name or (
                subject_tokens and subject_tokens.issubset(name_tokens)
            ):
                candidates.add((name.strip(), element_type, element.get("lane")))
    return candidates


def enforce_generic_target_ambiguity(
    request_text: str,
    catalogue: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Reject an over-specific model target inferred from a generic user reference."""

    normalized = dict(result)
    subject = _generic_subject(request_text)
    if subject is None:
        return normalized

    candidates = _catalogue_candidates(
        catalogue,
        subject,
        normalized.get("process_alias"),
    )
    if len(candidates) <= 1:
        return normalized

    normalized["target_query"] = None
    normalized["requires_clarification"] = True
    normalized["clarification_question"] = (
        f"Quelle activité liée à « {subject} » souhaitez-vous modifier ?"
    )
    confidence = normalized.get("confidence")
    normalized["confidence"] = min(float(confidence), 0.5) if isinstance(
        confidence, (int, float)
    ) and not isinstance(confidence, bool) else 0.5
    return normalized
