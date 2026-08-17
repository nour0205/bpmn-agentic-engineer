from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.models import BpmnElement, ElementCandidate


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    punctuation_normalized = re.sub(r"[^\w]+", " ", without_accents.casefold())
    return " ".join(punctuation_normalized.split())


@dataclass(frozen=True)
class GroundingResult:
    status: str
    selected: BpmnElement | None
    candidates: tuple[ElementCandidate, ...]
    reason: str


class ElementGrounder:
    """Resolve a textual target to exactly one process-aware BPMN element."""

    def __init__(self, document: BpmnDocument, inspector: ProcessInspector):
        self.document = document
        self.inspector = inspector

    def ground(
        self,
        *,
        target_query: str | None,
        target_element_id: str | None = None,
        process_id: str | None = None,
        lane_name: str | None = None,
        limit: int = 50,
    ) -> GroundingResult:
        if target_element_id:
            try:
                element = self.document.element(target_element_id)
            except KeyError:
                return GroundingResult(
                    status="not_found",
                    selected=None,
                    candidates=(),
                    reason=f"Unknown target element ID: {target_element_id}",
                )

            if process_id and element.process_id != process_id:
                return GroundingResult(
                    status="not_found",
                    selected=None,
                    candidates=(),
                    reason=(
                        f"Element {target_element_id!r} belongs to process "
                        f"{element.process_id!r}, not {process_id!r}."
                    ),
                )
            if lane_name and normalize_text(element.lane_name) != normalize_text(lane_name):
                return GroundingResult(
                    status="not_found",
                    selected=None,
                    candidates=(),
                    reason=(
                        f"Element {target_element_id!r} is assigned to lane "
                        f"{element.lane_name!r}, not {lane_name!r}."
                    ),
                )

            candidate = self._candidate(element, score=100.0, exact_name_match=True)
            return GroundingResult(
                status="resolved",
                selected=element,
                candidates=(candidate,),
                reason="Resolved by exact BPMN element ID.",
            )

        if not target_query or not target_query.strip():
            return GroundingResult(
                status="missing_target",
                selected=None,
                candidates=(),
                reason="No target element ID or textual target was provided.",
            )

        raw_matches = self.inspector.find_elements(target_query, limit=limit)
        filtered_matches: list[dict] = []
        normalized_lane = normalize_text(lane_name)

        for match in raw_matches:
            if process_id and match.get("process_id") != process_id:
                continue
            if lane_name and normalize_text(match.get("lane_name")) != normalized_lane:
                continue
            filtered_matches.append(match)

        candidates = tuple(
            self._candidate(
                self.document.element(match["id"]),
                score=float(match["score"]),
                exact_name_match=(
                    normalize_text(match.get("name")) == normalize_text(target_query)
                ),
            )
            for match in filtered_matches
        )

        if not candidates:
            return GroundingResult(
                status="not_found",
                selected=None,
                candidates=(),
                reason="No BPMN element matched the requested target and filters.",
            )

        exact_candidates = [candidate for candidate in candidates if candidate.exact_name_match]
        if len(exact_candidates) == 1:
            selected = self.document.element(exact_candidates[0].id)
            return GroundingResult(
                status="resolved",
                selected=selected,
                candidates=candidates,
                reason="Resolved by one exact normalized name match.",
            )
        if len(exact_candidates) > 1:
            return GroundingResult(
                status="ambiguous",
                selected=None,
                candidates=tuple(exact_candidates),
                reason=(
                    "Several elements have the same normalized name. "
                    "A process ID, lane, or exact element ID is required."
                ),
            )

        if len(candidates) == 1:
            return GroundingResult(
                status="resolved",
                selected=self.document.element(candidates[0].id),
                candidates=candidates,
                reason="Only one candidate matched the request.",
            )

        best = candidates[0]
        second = candidates[1]
        clearly_better = best.score >= 8.0 and (
            best.score >= second.score + 4.0
            or best.score >= second.score * 1.35
        )
        if clearly_better:
            return GroundingResult(
                status="resolved",
                selected=self.document.element(best.id),
                candidates=candidates,
                reason="The highest-scoring candidate was clearly better than alternatives.",
            )

        return GroundingResult(
            status="ambiguous",
            selected=None,
            candidates=candidates,
            reason=(
                "Several plausible BPMN elements matched the request and none was "
                "sufficiently dominant."
            ),
        )

    def _candidate(
        self,
        element: BpmnElement,
        *,
        score: float,
        exact_name_match: bool,
    ) -> ElementCandidate:
        process = self.document.processes.get(element.process_id or "", {})
        return ElementCandidate(
            id=element.id,
            type=element.type,
            name=element.name,
            process_id=element.process_id,
            participant_id=process.get("participant_id"),
            participant_name=process.get("participant_name"),
            lane_id=element.lane_id,
            lane_name=element.lane_name,
            score=round(score, 3),
            exact_name_match=exact_name_match,
        )
