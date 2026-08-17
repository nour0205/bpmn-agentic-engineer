from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SUPPORTED_OPERATIONS = {
    "insert_task_after",
    "insert_task_before",
    "rename_element",
    "remove_element",
    "replace_linear_task_sequence",
    "unsupported",
}

_ALLOWED_KEYS = {
    "schema_version",
    "operation",
    "target_query",
    "source_queries",
    "new_name",
    "new_bpmn_type",
    "lane_name",
    "process_alias",
    "requires_clarification",
    "clarification_question",
    "confidence",
}

_FORBIDDEN_KEYS = {
    "target_element_id",
    "element_id",
    "element_ids",
    "process_id",
    "lane_id",
    "sequence_flow_id",
    "sequence_flow_ids",
}

_ALLOWED_TASK_TYPES = {
    "task",
    "userTask",
    "manualTask",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "scriptTask",
    "businessRuleTask",
}


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null.")
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _text_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings.")
    cleaned: list[str] = []
    for index, item in enumerate(value):
        text = _optional_text(item, f"{field_name}[{index}]")
        if text:
            cleaned.append(text)
    return tuple(cleaned)


@dataclass(frozen=True)
class LlmInterpretation:
    """Strict, ID-free contract returned by the remote language model."""

    operation: str
    target_query: str | None
    new_name: str | None
    lane_name: str | None
    process_alias: str | None
    requires_clarification: bool
    clarification_question: str | None
    confidence: float
    source_queries: tuple[str, ...] = field(default_factory=tuple)
    new_bpmn_type: str | None = None
    schema_version: str = "1.1"

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        allowed_process_aliases: set[str] | None = None,
    ) -> "LlmInterpretation":
        if not isinstance(payload, dict):
            raise ValueError("The LLM interpretation must be one JSON object.")

        forbidden = sorted(_FORBIDDEN_KEYS & set(payload))
        if forbidden:
            raise ValueError(
                "The LLM is not allowed to return BPMN identifiers: " + ", ".join(forbidden)
            )

        unknown = sorted(set(payload) - _ALLOWED_KEYS)
        if unknown:
            raise ValueError("Unknown LLM interpretation fields: " + ", ".join(unknown))

        schema_version = payload.get("schema_version", "1.1")
        if schema_version not in {"1.0", "1.1"}:
            raise ValueError(f"Unsupported LLM interpretation schema: {schema_version!r}.")

        operation = payload.get("operation")
        if operation not in SUPPORTED_OPERATIONS:
            raise ValueError(
                "operation must be one of: " + ", ".join(sorted(SUPPORTED_OPERATIONS))
            )

        requires_clarification = payload.get("requires_clarification")
        if not isinstance(requires_clarification, bool):
            raise ValueError("requires_clarification must be a boolean.")

        confidence_raw = payload.get("confidence")
        if isinstance(confidence_raw, bool) or not isinstance(confidence_raw, (int, float)):
            raise ValueError("confidence must be a number between 0 and 1.")
        confidence = float(confidence_raw)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")

        process_alias = _optional_text(payload.get("process_alias"), "process_alias")
        if (
            process_alias is not None
            and allowed_process_aliases is not None
            and process_alias not in allowed_process_aliases
        ):
            raise ValueError(f"Unknown process alias returned by the LLM: {process_alias!r}.")

        new_bpmn_type = _optional_text(payload.get("new_bpmn_type"), "new_bpmn_type")
        if new_bpmn_type is not None and new_bpmn_type not in _ALLOWED_TASK_TYPES:
            raise ValueError(
                "new_bpmn_type must be one of: " + ", ".join(sorted(_ALLOWED_TASK_TYPES))
            )

        interpretation = cls(
            operation=operation,
            target_query=_optional_text(payload.get("target_query"), "target_query"),
            source_queries=_text_list(payload.get("source_queries"), "source_queries"),
            new_name=_optional_text(payload.get("new_name"), "new_name"),
            new_bpmn_type=new_bpmn_type,
            lane_name=_optional_text(payload.get("lane_name"), "lane_name"),
            process_alias=process_alias,
            requires_clarification=requires_clarification,
            clarification_question=_optional_text(
                payload.get("clarification_question"), "clarification_question"
            ),
            confidence=confidence,
            schema_version="1.1" if operation == "replace_linear_task_sequence" else schema_version,
        )
        interpretation._validate_semantics()
        return interpretation

    def _validate_semantics(self) -> None:
        if self.operation in {"insert_task_after", "insert_task_before"} and not self.new_name:
            if not self.requires_clarification:
                raise ValueError("Insertion requires new_name or requires_clarification=true.")
        if self.operation == "rename_element" and not self.new_name:
            if not self.requires_clarification:
                raise ValueError("Renaming requires new_name or requires_clarification=true.")
        if self.operation == "replace_linear_task_sequence":
            if len(self.source_queries) < 2 and not self.requires_clarification:
                raise ValueError(
                    "Linear sequence replacement requires at least two source_queries."
                )
            if not self.new_name and not self.requires_clarification:
                raise ValueError("Linear sequence replacement requires new_name.")
        elif self.source_queries:
            raise ValueError(
                "source_queries is only allowed for replace_linear_task_sequence."
            )
        if (
            self.operation not in {"unsupported", "replace_linear_task_sequence"}
            and not self.target_query
            and not self.requires_clarification
        ):
            raise ValueError("A supported operation requires target_query or clarification.")
        if self.requires_clarification and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when requires_clarification=true."
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_queries"] = list(self.source_queries)
        return data
