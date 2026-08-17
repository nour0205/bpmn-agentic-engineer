from __future__ import annotations

from collections import deque
from typing import Any

from bpmn_agentic_engineer.bpmn.document import BpmnDocument
from bpmn_agentic_engineer.models import ValidationIssue


class BasicValidator:
    """Deterministic structural checks.

    This validator distinguishes:
    - blocking structural errors;
    - non-blocking modelling warnings;
    - informational BPMN patterns such as implicit entries and exits.

    It is intentionally not a complete BPMN 2.0 semantic validator.
    """

    def __init__(self, document: BpmnDocument):
        self.document = document

    def validate(self) -> dict[str, Any]:
        issues: list[ValidationIssue] = []
        issues.extend(self._duplicate_id_issues())
        issues.extend(self._reference_issues())
        issues.extend(self._process_boundary_issues())
        issues.extend(self._connectivity_issues())

        severity_order = {"error": 0, "warning": 1, "info": 2}
        issues.sort(
            key=lambda item: (
                severity_order.get(item.severity, 99),
                item.code,
                item.element_ids,
            )
        )

        return {
            "file": str(self.document.path),
            "valid_for_agentic_editing": not any(
                issue.severity == "error" for issue in issues
            ),
            "error_count": sum(issue.severity == "error" for issue in issues),
            "warning_count": sum(issue.severity == "warning" for issue in issues),
            "info_count": sum(issue.severity == "info" for issue in issues),
            "issues": [issue.to_dict() for issue in issues],
            "scope_note": (
                "Basic structural validation only; full BPMN XSD and execution "
                "semantics will be added in a later milestone."
            ),
        }

    def _process_elements(self, process_id: str):
        return [
            element
            for element in self.document.elements.values()
            if element.process_id == process_id
        ]

    def _boundary_ids(
        self,
        process_id: str,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """Return explicit starts, implicit starts, explicit ends and implicit ends."""
        process_elements = self._process_elements(process_id)

        explicit_start_ids = [
            element.id
            for element in process_elements
            if element.type == "startEvent"
        ]
        explicit_end_ids = [
            element.id
            for element in process_elements
            if element.type == "endEvent"
        ]

        implicit_start_ids = [
            element.id
            for element in process_elements
            if element.type != "boundaryEvent"
            and not self.document.incoming.get(element.id)
        ]
        implicit_end_ids = [
            element.id
            for element in process_elements
            if element.type != "boundaryEvent"
            and not self.document.outgoing.get(element.id)
        ]

        return (
            explicit_start_ids,
            implicit_start_ids,
            explicit_end_ids,
            implicit_end_ids,
        )

    def _duplicate_id_issues(self) -> list[ValidationIssue]:
        return [
            ValidationIssue(
                code="DUPLICATE_ID",
                severity="error",
                message=f"Identifier {identifier!r} appears more than once.",
                element_ids=(identifier,),
            )
            for identifier in self.document.duplicate_ids()
        ]

    def _reference_issues(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        known_nodes = set(self.document.elements)

        for flow in self.document.sequence_flows.values():
            missing: list[str] = []

            if flow.source_ref not in known_nodes:
                missing.append(flow.source_ref)
            if flow.target_ref not in known_nodes:
                missing.append(flow.target_ref)

            if missing:
                issues.append(
                    ValidationIssue(
                        code="DANGLING_SEQUENCE_FLOW",
                        severity="error",
                        message=(
                            f"Sequence flow {flow.id!r} references unknown flow "
                            f"node(s): {', '.join(missing)}."
                        ),
                        element_ids=(flow.id, *missing),
                    )
                )

        return issues

    def _process_boundary_issues(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        for process_id in self.document.processes:
            process_elements = self._process_elements(process_id)

            if not process_elements:
                issues.append(
                    ValidationIssue(
                        code="EMPTY_PROCESS_CONTAINER",
                        severity="info",
                        message=f"Process {process_id!r} is an empty pool/container.",
                        element_ids=(process_id,),
                    )
                )
                continue

            (
                explicit_start_ids,
                implicit_start_ids,
                explicit_end_ids,
                implicit_end_ids,
            ) = self._boundary_ids(process_id)

            entry_ids = explicit_start_ids or implicit_start_ids
            exit_ids = explicit_end_ids or implicit_end_ids

            if explicit_end_ids and not explicit_start_ids:
                issues.append(
                    ValidationIssue(
                        code="EXPLICIT_END_WITH_IMPLICIT_START",
                        severity="warning",
                        message=(
                            f"Process {process_id!r} has an explicit end event but "
                            "uses an implicit process entry."
                        ),
                        element_ids=(process_id, *implicit_start_ids),
                    )
                )
            elif not explicit_start_ids and implicit_start_ids:
                issues.append(
                    ValidationIssue(
                        code="IMPLICIT_START_NODE",
                        severity="info",
                        message=(
                            f"Process {process_id!r} uses implicit process entry "
                            f"node(s): {', '.join(implicit_start_ids)}."
                        ),
                        element_ids=(process_id, *implicit_start_ids),
                    )
                )

            if not explicit_end_ids and implicit_end_ids:
                issues.append(
                    ValidationIssue(
                        code="IMPLICIT_END_NODE",
                        severity="info",
                        message=(
                            f"Process {process_id!r} uses implicit process exit "
                            f"node(s): {', '.join(implicit_end_ids)}."
                        ),
                        element_ids=(process_id, *implicit_end_ids),
                    )
                )

            if not entry_ids:
                issues.append(
                    ValidationIssue(
                        code="MISSING_START_EVENT",
                        severity="error",
                        message=(
                            f"Process {process_id!r} has no explicit or implicit "
                            "entry node."
                        ),
                        element_ids=(process_id,),
                    )
                )

            if not exit_ids:
                issues.append(
                    ValidationIssue(
                        code="MISSING_END_EVENT",
                        severity="error",
                        message=(
                            f"Process {process_id!r} has no explicit or implicit "
                            "exit node."
                        ),
                        element_ids=(process_id,),
                    )
                )

        return issues

    def _connectivity_issues(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        recognized_implicit_entry_ids: set[str] = set()
        recognized_implicit_exit_ids: set[str] = set()

        for process_id in self.document.processes:
            if not self._process_elements(process_id):
                continue

            (
                explicit_start_ids,
                implicit_start_ids,
                explicit_end_ids,
                implicit_end_ids,
            ) = self._boundary_ids(process_id)

            if not explicit_start_ids:
                recognized_implicit_entry_ids.update(implicit_start_ids)
            if not explicit_end_ids:
                recognized_implicit_exit_ids.update(implicit_end_ids)

        for element in self.document.elements.values():
            incoming = self.document.incoming.get(element.id, [])
            outgoing = self.document.outgoing.get(element.id, [])

            if (
                element.type not in {"startEvent", "boundaryEvent"}
                and not incoming
                and element.id not in recognized_implicit_entry_ids
            ):
                issues.append(
                    ValidationIssue(
                        code="NO_INCOMING_FLOW",
                        severity="warning",
                        message=(
                            f"{element.type} {element.id!r} has no incoming "
                            "sequence flow."
                        ),
                        element_ids=(element.id,),
                    )
                )

            if (
                element.type not in {"endEvent", "boundaryEvent"}
                and not outgoing
                and element.id not in recognized_implicit_exit_ids
            ):
                issues.append(
                    ValidationIssue(
                        code="NO_OUTGOING_FLOW",
                        severity="warning",
                        message=(
                            f"{element.type} {element.id!r} has no outgoing "
                            "sequence flow."
                        ),
                        element_ids=(element.id,),
                    )
                )

        for process_id in self.document.processes:
            process_node_ids = {
                element.id
                for element in self.document.elements.values()
                if element.process_id == process_id
            }

            if not process_node_ids:
                continue

            (
                explicit_start_ids,
                implicit_start_ids,
                explicit_end_ids,
                implicit_end_ids,
            ) = self._boundary_ids(process_id)

            entry_ids = explicit_start_ids or implicit_start_ids
            exit_ids = explicit_end_ids or implicit_end_ids

            if not entry_ids:
                continue

            reachable: set[str] = set(entry_ids)
            queue: deque[str] = deque(entry_ids)

            while queue:
                current = queue.popleft()

                for successor in self.document.outgoing.get(current, []):
                    if (
                        successor in process_node_ids
                        and successor not in reachable
                    ):
                        reachable.add(successor)
                        queue.append(successor)

            for unreachable_id in sorted(process_node_ids - reachable):
                issues.append(
                    ValidationIssue(
                        code="UNREACHABLE_NODE",
                        severity="warning",
                        message=(
                            f"Flow node {unreachable_id!r} is not reachable from "
                            f"a process entry in process {process_id!r}."
                        ),
                        element_ids=(unreachable_id,),
                    )
                )

            if exit_ids and not any(exit_id in reachable for exit_id in exit_ids):
                issues.append(
                    ValidationIssue(
                        code="NO_REACHABLE_END_EVENT",
                        severity="error",
                        message=(
                            f"No process exit is reachable in process "
                            f"{process_id!r}."
                        ),
                        element_ids=(process_id, *exit_ids),
                    )
                )

        return issues
