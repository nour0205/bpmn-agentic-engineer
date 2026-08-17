from __future__ import annotations

import re
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.bpmn.document import local_name
from bpmn_agentic_engineer.models import (
    ChangeRequest,
    ModificationPlan,
    PlannedOperation,
)
from bpmn_agentic_engineer.planning.grounding import ElementGrounder, normalize_text
from bpmn_agentic_engineer.validation import BasicValidator
from bpmn_agentic_engineer.integrity import attach_plan_integrity


_QUOTED_TEXT = re.compile(r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"")


def _quoted_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    for match in _QUOTED_TEXT.finditer(text):
        fragment = next(group for group in match.groups() if group is not None)
        cleaned = " ".join(fragment.split()).strip(" .,:;\t\r\n")
        if cleaned:
            fragments.append(cleaned)
    return fragments


def _clean_fragment(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip(" .,:;\t\r\n")
    cleaned = re.sub(
        r"^(?:la|le|les|l['’]|une|un|the|a|an)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned or None


class ChangeRequestParser:
    """Small deterministic parser for the first planning milestone.

    The MCP tool also accepts explicit hints. Those hints always take priority
    over values inferred from the natural-language request.
    """

    def parse(
        self,
        request_text: str,
        *,
        operation_hint: str | None = None,
        target_query: str | None = None,
        target_element_id: str | None = None,
        process_id: str | None = None,
        new_name: str | None = None,
        lane_name: str | None = None,
        source_queries: list[str] | tuple[str, ...] | None = None,
        new_bpmn_type: str | None = None,
    ) -> ChangeRequest:
        if not request_text or not request_text.strip():
            raise ValueError("Change request cannot be empty.")

        normalized = normalize_text(request_text)
        quoted = _quoted_fragments(request_text)

        operation = "unsupported"
        position: str | None = None
        inferred_target: str | None = None
        inferred_new_name: str | None = None
        inferred_sources: list[str] = []
        inferred_bpmn_type: str | None = None

        if any(
            keyword in normalized
            for keyword in ("fusionner", "fusionne", "regrouper", "consolider", "merge")
        ):
            operation = "replace_linear_task_sequence"
            if len(quoted) >= 3:
                inferred_sources = quoted[:-1]
                inferred_new_name = quoted[-1]
            if any(
                phrase in normalized
                for phrase in ("tache de service", "service task", "automatiser", "automatisee")
            ):
                inferred_bpmn_type = "serviceTask"
            elif "tache manuelle" in normalized or "manual task" in normalized:
                inferred_bpmn_type = "manualTask"
            elif "tache utilisateur" in normalized or "user task" in normalized:
                inferred_bpmn_type = "userTask"

        elif any(keyword in normalized for keyword in ("renommer", "rename")):
            operation = "rename_element"
            if len(quoted) >= 2:
                inferred_target, inferred_new_name = quoted[0], quoted[1]
            else:
                rename_match = re.search(
                    r"(?:renommer|rename)\s+(.+?)\s+(?:en|to)\s+(.+)$",
                    request_text,
                    flags=re.IGNORECASE,
                )
                if rename_match:
                    inferred_target = _clean_fragment(rename_match.group(1))
                    inferred_new_name = _clean_fragment(rename_match.group(2))

        elif any(keyword in normalized for keyword in ("supprimer", "retirer", "remove", "delete")):
            operation = "remove_element"
            if quoted:
                inferred_target = quoted[0]
            else:
                remove_match = re.search(
                    r"(?:supprimer|retirer|remove|delete)\s+(.+)$",
                    request_text,
                    flags=re.IGNORECASE,
                )
                if remove_match:
                    inferred_target = _clean_fragment(remove_match.group(1))

        elif any(
            keyword in normalized
            for keyword in ("ajouter", "inserer", "creer", "add", "insert", "create")
        ):
            if " apres " in f" {normalized} " or " after " in f" {normalized} ":
                operation = "insert_task_after"
                position = "after"
            elif " avant " in f" {normalized} " or " before " in f" {normalized} ":
                operation = "insert_task_before"
                position = "before"
            else:
                operation = "insert_task"

            if len(quoted) >= 2:
                inferred_new_name, inferred_target = quoted[0], quoted[1]
            else:
                add_match = re.search(
                    r"(?:ajouter|ins[ée]rer|creer|cr[ée]er|add|insert|create)\s+"
                    r"(?:une?\s+|a\s+|an\s+)?"
                    r"(?:nouvelle?\s+|new\s+)?"
                    r"(?:t[âa]che|activit[ée]|task|activity)\s+(.+?)\s+"
                    r"(?:juste\s+|directement\s+|immediately\s+)?"
                    r"(?:apr[èe]s|after|avant|before)\s+(.+)$",
                    request_text,
                    flags=re.IGNORECASE,
                )
                if add_match:
                    inferred_new_name = _clean_fragment(add_match.group(1))
                    inferred_target = _clean_fragment(add_match.group(2))
                elif len(quoted) == 1:
                    position_index = max(
                        normalized.find(" apres "),
                        normalized.find(" after "),
                        normalized.find(" avant "),
                        normalized.find(" before "),
                    )
                    quote_index = request_text.find(quoted[0])
                    if position_index >= 0 and quote_index >= 0:
                        # A single quote after the position word is most likely the target.
                        if quote_index > position_index:
                            inferred_target = quoted[0]
                        else:
                            inferred_new_name = quoted[0]

        if operation_hint is not None:
            allowed_operations = {
                "insert_task_after",
                "insert_task_before",
                "rename_element",
                "remove_element",
                "replace_linear_task_sequence",
                "unsupported",
            }
            if operation_hint not in allowed_operations:
                raise ValueError(f"Unsupported explicit operation hint: {operation_hint!r}.")
            operation = operation_hint
            if operation_hint == "insert_task_after":
                position = "after"
            elif operation_hint == "insert_task_before":
                position = "before"
            else:
                position = None

        return ChangeRequest(
            request_text=" ".join(request_text.split()),
            operation=operation,
            position=position,
            target_query=_clean_fragment(target_query) or inferred_target,
            target_element_id=target_element_id,
            target_process_id=process_id,
            new_name=_clean_fragment(new_name) or inferred_new_name,
            target_lane_name=_clean_fragment(lane_name),
            source_queries=tuple(
                cleaned
                for value in (source_queries or inferred_sources)
                if (cleaned := _clean_fragment(value))
            ),
            new_bpmn_type=_clean_fragment(new_bpmn_type) or inferred_bpmn_type,
        )


class ChangePlanner:
    """Generate a safe, read-only modification plan for one BPMN document."""

    def __init__(self, document: BpmnDocument, inspector: ProcessInspector | None = None):
        self.document = document
        self.inspector = inspector or ProcessInspector(document)
        self.parser = ChangeRequestParser()
        self.grounder = ElementGrounder(document, self.inspector)

    def _plan_without_integrity(
        self,
        request_text: str,
        *,
        operation: str | None = None,
        target_query: str | None = None,
        target_element_id: str | None = None,
        process_id: str | None = None,
        new_name: str | None = None,
        lane_name: str | None = None,
        source_queries: list[str] | tuple[str, ...] | None = None,
        new_bpmn_type: str | None = None,
    ) -> dict[str, Any]:
        request = self.parser.parse(
            request_text,
            operation_hint=operation,
            target_query=target_query,
            target_element_id=target_element_id,
            process_id=process_id,
            new_name=new_name,
            lane_name=lane_name,
            source_queries=source_queries,
            new_bpmn_type=new_bpmn_type,
        )

        validation = BasicValidator(self.document).validate()
        validation_summary = {
            "valid_for_agentic_editing": validation["valid_for_agentic_editing"],
            "error_count": validation["error_count"],
            "warning_count": validation["warning_count"],
            "info_count": validation.get("info_count", 0),
            "blocking_issues": [
                issue for issue in validation["issues"] if issue["severity"] == "error"
            ],
        }

        if not validation["valid_for_agentic_editing"]:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="blocked_by_baseline_errors",
                requires_clarification=False,
                requires_approval=False,
                risks=(
                    "The source BPMN has blocking structural errors and must not be edited.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        request_questions = self._request_questions(request)
        if request.operation == "unsupported":
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="unsupported_request",
                requires_clarification=True,
                requires_approval=False,
                clarification_questions=(
                    "Use one supported operation: insert a task before/after, rename an element, "
                    "remove a simple element, or replace a consecutive linear task sequence.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        if request_questions:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                clarification_questions=tuple(request_questions),
                baseline_validation=validation_summary,
            ).to_dict()

        if request.operation == "replace_linear_task_sequence":
            return self._plan_linear_task_replacement(request, validation_summary)

        # For insertion operations, lane_name describes where the new task must
        # be created. It must not filter the existing anchor task, which may be
        # located in a different lane. For rename/remove, it remains a grounding
        # constraint for the existing target.
        grounding_lane_name = (
            None
            if request.operation in {"insert_task_after", "insert_task_before"}
            else request.target_lane_name
        )
        grounding = self.grounder.ground(
            target_query=request.target_query,
            target_element_id=request.target_element_id,
            process_id=request.target_process_id,
            lane_name=grounding_lane_name,
        )
        candidate_payloads = tuple(candidate.to_dict() for candidate in grounding.candidates)

        if grounding.status != "resolved" or grounding.selected is None:
            questions = [self._grounding_question(grounding.status, grounding.reason)]
            if grounding.status == "ambiguous":
                questions.append(
                    "Choose one candidate by supplying target_element_id or target_process_id."
                )
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                candidate_matches=candidate_payloads,
                clarification_questions=tuple(questions),
                baseline_validation=validation_summary,
            ).to_dict()

        selected = grounding.selected
        selected_payload = self._selected_target_payload(selected)
        context = self.inspector.element_context(selected.id)

        plan_result = self._build_operations(request, context)
        if plan_result["clarification_questions"]:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                selected_target=selected_payload,
                candidate_matches=candidate_payloads,
                target_context=context,
                risks=tuple(plan_result["risks"]),
                clarification_questions=tuple(plan_result["clarification_questions"]),
                baseline_validation=validation_summary,
            ).to_dict()

        return ModificationPlan(
            file=str(self.document.path),
            request=request,
            status="ready_for_approval",
            requires_clarification=False,
            requires_approval=True,
            selected_target=selected_payload,
            candidate_matches=candidate_payloads,
            target_context=context,
            planned_operations=tuple(plan_result["operations"]),
            acceptance_criteria=tuple(plan_result["acceptance_criteria"]),
            risks=tuple(plan_result["risks"]),
            assumptions=tuple(plan_result["assumptions"]),
            baseline_validation=validation_summary,
        ).to_dict()

    def plan(
        self,
        request_text: str,
        *,
        operation: str | None = None,
        target_query: str | None = None,
        target_element_id: str | None = None,
        process_id: str | None = None,
        new_name: str | None = None,
        lane_name: str | None = None,
        source_queries: list[str] | tuple[str, ...] | None = None,
        new_bpmn_type: str | None = None,
    ) -> dict[str, Any]:
        result = self._plan_without_integrity(
            request_text,
            operation=operation,
            target_query=target_query,
            target_element_id=target_element_id,
            process_id=process_id,
            new_name=new_name,
            lane_name=lane_name,
            source_queries=source_queries,
            new_bpmn_type=new_bpmn_type,
        )
        result["candidate_matches"] = self._compact_candidates(
            result.get("candidate_matches", [])
        )
        return attach_plan_integrity(result, self.document.path)

    @staticmethod
    def _compact_candidates(
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        exact = [candidate for candidate in candidates if candidate.get("exact_name_match")]
        if exact:
            return exact[:10]
        best_score = float(candidates[0].get("score", 0.0))
        threshold = max(3.0, best_score * 0.35)
        return [
            candidate
            for candidate in candidates
            if float(candidate.get("score", 0.0)) >= threshold
        ][:10]

    def _request_questions(self, request: ChangeRequest) -> list[str]:
        questions: list[str] = []
        if (
            request.operation != "replace_linear_task_sequence"
            and not request.target_element_id
            and not request.target_query
        ):
            questions.append("Which existing BPMN element should be changed?")
        if request.operation in {"insert_task_after", "insert_task_before", "insert_task"}:
            if not request.new_name:
                questions.append("What should the new task be called?")
            if request.operation == "insert_task":
                questions.append("Should the new task be inserted before or after the target?")
        if request.operation == "rename_element" and not request.new_name:
            questions.append("What should the new element name be?")
        if request.operation == "replace_linear_task_sequence":
            if len(request.source_queries) < 2:
                questions.append("Which two or more consecutive tasks should be replaced?")
            if not request.new_name:
                questions.append("What should the consolidated task be called?")
        return questions

    @staticmethod
    def _grounding_question(status: str, reason: str) -> str:
        if status == "not_found":
            return f"The target could not be found. {reason}"
        if status == "missing_target":
            return "Provide a target task name or an exact target_element_id."
        return f"The target is ambiguous. {reason}"

    def _selected_target_payload(self, element) -> dict[str, Any]:
        process = self.document.processes.get(element.process_id or "", {})
        return {
            **element.to_dict(),
            "participant_id": process.get("participant_id"),
            "participant_name": process.get("participant_name"),
        }

    def _plan_linear_task_replacement(
        self,
        request: ChangeRequest,
        validation_summary: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_payloads: list[dict[str, Any]] = []
        resolved_elements = []

        for query in request.source_queries:
            grounding = self.grounder.ground(
                target_query=query,
                process_id=request.target_process_id,
            )
            candidate_payloads.extend(
                candidate.to_dict() for candidate in grounding.candidates
            )
            if grounding.status != "resolved" or grounding.selected is None:
                question = (
                    f"The source task {query!r} could not be resolved. "
                    f"{grounding.reason}"
                )
                if grounding.status == "ambiguous":
                    question += " Supply a process ID or use more precise visible labels."
                return ModificationPlan(
                    file=str(self.document.path),
                    request=request,
                    status="requires_clarification",
                    requires_clarification=True,
                    requires_approval=False,
                    candidate_matches=tuple(candidate_payloads),
                    clarification_questions=(question,),
                    baseline_validation=validation_summary,
                ).to_dict()
            resolved_elements.append(grounding.selected)

        resolved_ids = [element.id for element in resolved_elements]
        if len(set(resolved_ids)) != len(resolved_ids):
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                candidate_matches=tuple(candidate_payloads),
                clarification_questions=(
                    "Two source labels resolved to the same BPMN element. "
                    "Provide distinct visible task labels.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        process_ids = {element.process_id for element in resolved_elements}
        if len(process_ids) != 1 or None in process_ids:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                candidate_matches=tuple(candidate_payloads),
                risks=("The selected tasks do not belong to one BPMN process.",),
                clarification_questions=(
                    "All tasks in a replacement sequence must belong to the same process.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()
        process_id = next(iter(process_ids))

        allowed_task_types = {
            "task",
            "userTask",
            "manualTask",
            "serviceTask",
            "sendTask",
            "receiveTask",
            "scriptTask",
            "businessRuleTask",
        }
        invalid_types = [
            element for element in resolved_elements if element.type not in allowed_task_types
        ]
        if invalid_types:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                risks=("The selected sequence contains a non-task flow node.",),
                clarification_questions=(
                    "Only task-like BPMN elements can be consolidated in this milestone.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        ordered, ordering_error = self._order_selected_linear_sequence(resolved_elements)
        if ordering_error:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                candidate_matches=tuple(candidate_payloads),
                risks=("The selected tasks are not one unbranched consecutive sequence.",),
                clarification_questions=(ordering_error,),
                baseline_validation=validation_summary,
            ).to_dict()

        contexts = [self.inspector.element_context(element.id) for element in ordered]
        for context in contexts:
            incoming = context["incoming_sequence_flows"]
            outgoing = context["outgoing_sequence_flows"]
            if len(incoming) != 1 or len(outgoing) != 1:
                return ModificationPlan(
                    file=str(self.document.path),
                    request=request,
                    status="requires_clarification",
                    requires_clarification=True,
                    requires_approval=False,
                    selected_target=context["element"],
                    risks=(
                        "At least one selected task has multiple or missing incoming/outgoing flows.",
                    ),
                    clarification_questions=(
                        "Sequence replacement is allowed only when every selected task has "
                        "exactly one incoming and one outgoing sequence flow.",
                    ),
                    baseline_validation=validation_summary,
                ).to_dict()

        first_context = contexts[0]
        last_context = contexts[-1]
        incoming_flow = first_context["incoming_sequence_flows"][0]
        outgoing_flow = last_context["outgoing_sequence_flows"][0]
        internal_flows: list[dict[str, Any]] = []
        for left, right in zip(ordered, ordered[1:]):
            matches = [
                flow.to_dict()
                for flow in self.document.sequence_flows.values()
                if flow.source_ref == left.id and flow.target_ref == right.id
            ]
            if len(matches) != 1:
                return ModificationPlan(
                    file=str(self.document.path),
                    request=request,
                    status="requires_clarification",
                    requires_clarification=True,
                    requires_approval=False,
                    risks=("The selected tasks are not directly connected in one sequence.",),
                    clarification_questions=(
                        f"Tasks {left.name!r} and {right.name!r} must be directly connected.",
                    ),
                    baseline_validation=validation_summary,
                ).to_dict()
            internal_flows.append(matches[0])

        relevant_flows = [incoming_flow, *internal_flows, outgoing_flow]
        if any(flow.get("condition_expression") for flow in relevant_flows):
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                risks=("A sequence flow in or around the selection has a condition.",),
                clarification_questions=(
                    "Conditional flows cannot be rewritten by linear sequence replacement.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        selected_ids = {element.id for element in ordered}
        attached_boundaries = [
            element.attrib.get("id")
            for element in self.document.root.iter()
            if local_name(element.tag) == "boundaryEvent"
            and element.attrib.get("attachedToRef") in selected_ids
        ]
        if attached_boundaries:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                risks=("A selected task has an attached boundary event.",),
                clarification_questions=(
                    "Remove or explicitly redesign attached boundary events before consolidating "
                    "this sequence.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        lane_id, lane_name, lane_error = self._resolve_replacement_lane(
            process_id, ordered, request.target_lane_name
        )
        if lane_error:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                clarification_questions=(lane_error,),
                baseline_validation=validation_summary,
            ).to_dict()

        new_bpmn_type = request.new_bpmn_type or "task"
        if new_bpmn_type not in allowed_task_types:
            return ModificationPlan(
                file=str(self.document.path),
                request=request,
                status="requires_clarification",
                requires_clarification=True,
                requires_approval=False,
                clarification_questions=(
                    f"Unsupported replacement task type: {new_bpmn_type!r}.",
                ),
                baseline_validation=validation_summary,
            ).to_dict()

        operation_index = 1
        operations: list[PlannedOperation] = []
        for flow in relevant_flows:
            operations.append(
                PlannedOperation(
                    id=f"op_{operation_index:03d}",
                    operation="remove_sequence_flow",
                    parameters={"sequence_flow_id": flow["id"]},
                    rationale="Detach the old linear task sequence safely.",
                )
            )
            operation_index += 1

        for element in ordered:
            operations.append(
                PlannedOperation(
                    id=f"op_{operation_index:03d}",
                    operation="remove_element",
                    parameters={"element_id": element.id},
                    rationale="Remove one fragmented task from the approved sequence.",
                )
            )
            operation_index += 1

        operations.append(
            PlannedOperation(
                id=f"op_{operation_index:03d}",
                operation="add_task",
                parameters={
                    "new_element_id": "${new_task_id}",
                    "name": request.new_name,
                    "process_id": process_id,
                    "lane_id": lane_id,
                    "lane_name": lane_name,
                    "bpmn_type": new_bpmn_type,
                    "layout_mode": "replace_sequence",
                    "diagram_anchor": self._replacement_diagram_anchor(ordered),
                },
                rationale="Create the consolidated replacement task.",
            )
        )
        operation_index += 1

        operations.append(
            PlannedOperation(
                id=f"op_{operation_index:03d}",
                operation="add_sequence_flow",
                parameters={
                    "new_sequence_flow_id": "${new_flow_1_id}",
                    "source_ref": incoming_flow["source_ref"],
                    "target_ref": "${new_task_id}",
                    "process_id": process_id,
                    "preserve_name": incoming_flow.get("name"),
                    "preserve_condition_expression": None,
                },
                rationale="Connect the original predecessor to the consolidated task.",
            )
        )
        operation_index += 1
        operations.append(
            PlannedOperation(
                id=f"op_{operation_index:03d}",
                operation="add_sequence_flow",
                parameters={
                    "new_sequence_flow_id": "${new_flow_2_id}",
                    "source_ref": "${new_task_id}",
                    "target_ref": outgoing_flow["target_ref"],
                    "process_id": process_id,
                    "preserve_name": outgoing_flow.get("name"),
                    "preserve_condition_expression": None,
                },
                rationale="Reconnect the consolidated task to the original successor.",
            )
        )

        selected_target = self._selected_target_payload(ordered[0])
        selected_target["sequence"] = [
            self._selected_target_payload(element) for element in ordered
        ]
        predecessor = self.document.elements.get(incoming_flow["source_ref"])
        successor = self.document.elements.get(outgoing_flow["target_ref"])

        return ModificationPlan(
            file=str(self.document.path),
            request=request,
            status="ready_for_approval",
            requires_clarification=False,
            requires_approval=True,
            selected_target=selected_target,
            candidate_matches=tuple(candidate_payloads),
            target_context={
                "sequence": [context["element"] for context in contexts],
                "predecessor": predecessor.to_dict() if predecessor else None,
                "successor": successor.to_dict() if successor else None,
                "incoming_sequence_flow": incoming_flow,
                "internal_sequence_flows": internal_flows,
                "outgoing_sequence_flow": outgoing_flow,
            },
            planned_operations=tuple(operations),
            acceptance_criteria=(
                f"The {len(ordered)} fragmented tasks no longer exist.",
                f"One {new_bpmn_type} named {request.new_name!r} replaces the sequence.",
                "The original predecessor connects to the consolidated task.",
                "The consolidated task connects to the original successor.",
                "No sequence flow references an unknown element.",
                "All unrelated BPMN elements remain unchanged.",
            ),
            risks=(
                "Documentation, data associations, and implementation details attached to the "
                "removed tasks must be reviewed and migrated when relevant.",
            ),
            assumptions=(
                "The selected task sequence is intentionally replaced as one business activity.",
                "The replacement task uses the approved BPMN type and lane.",
            ),
            baseline_validation=validation_summary,
        ).to_dict()

    def _order_selected_linear_sequence(self, elements):
        selected = {element.id: element for element in elements}
        selected_ids = set(selected)
        starts = [
            element_id
            for element_id in selected_ids
            if not any(
                predecessor in selected_ids
                for predecessor in self.document.incoming.get(element_id, [])
            )
        ]
        if len(starts) != 1:
            return [], (
                "The selected tasks must form one consecutive linear chain with exactly one start."
            )

        ordered = []
        current = starts[0]
        visited: set[str] = set()
        while current in selected_ids and current not in visited:
            visited.add(current)
            ordered.append(selected[current])
            next_nodes = [
                successor
                for successor in self.document.outgoing.get(current, [])
                if successor in selected_ids
            ]
            if len(next_nodes) > 1:
                return [], "The selected tasks contain an internal branch."
            if not next_nodes:
                break
            current = next_nodes[0]

        if visited != selected_ids:
            return [], "The selected tasks are not one directly connected sequence."
        return ordered, None

    def _resolve_replacement_lane(self, process_id, elements, requested_lane_name):
        if requested_lane_name:
            normalized = normalize_text(requested_lane_name)
            matches = [
                lane
                for lane in self.document.lanes.values()
                if lane.get("process_id") == process_id
                and normalize_text(lane.get("name")) == normalized
            ]
            if len(matches) == 1:
                return matches[0]["id"], matches[0].get("name"), None
            if not matches:
                return None, None, (
                    f"No lane named {requested_lane_name!r} exists in the selected process."
                )
            return None, None, (
                f"Several lanes named {requested_lane_name!r} exist; provide a unique lane."
            )

        lane_pairs = {(element.lane_id, element.lane_name) for element in elements}
        if len(lane_pairs) == 1:
            lane_id, lane_name = next(iter(lane_pairs))
            return lane_id, lane_name, None
        return None, None, (
            "The selected tasks span several lanes. Specify the lane for the consolidated task."
        )

    def _resolve_insertion_lane(
        self,
        process_id: str,
        requested_lane_name: str | None,
        fallback_lane_id: str | None,
        fallback_lane_name: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve the destination lane for a newly inserted task.

        The requested lane belongs to the new task, not to the existing anchor.
        When no lane is requested, preserve the anchor task's lane.
        """
        if not requested_lane_name:
            return fallback_lane_id, fallback_lane_name, None

        normalized = normalize_text(requested_lane_name)
        matches = [
            lane
            for lane in self.document.lanes.values()
            if lane.get("process_id") == process_id
            and normalize_text(lane.get("name")) == normalized
        ]
        if len(matches) == 1:
            return matches[0]["id"], matches[0].get("name"), None
        if not matches:
            return None, None, (
                f"No lane named {requested_lane_name!r} exists in the target process."
            )
        return None, None, (
            f"Several lanes named {requested_lane_name!r} exist in the target process; "
            "provide a unique lane."
        )

    @staticmethod
    def _resolve_new_task_type(request: ChangeRequest) -> tuple[str | None, str | None]:
        allowed = {
            "task",
            "userTask",
            "manualTask",
            "serviceTask",
            "sendTask",
            "receiveTask",
            "scriptTask",
            "businessRuleTask",
        }
        task_type = request.new_bpmn_type or "task"
        if task_type not in allowed:
            return None, f"Unsupported new task type: {task_type!r}."
        return task_type, None

    def _replacement_diagram_anchor(self, elements) -> dict[str, float] | None:
        bounds = [
            shape
            for element in elements
            for shape in self.document.shapes.get(element.id, [])[:1]
        ]
        if not bounds:
            return None
        first = bounds[0]
        left = min(item.x for item in bounds)
        right = max(item.right for item in bounds)
        width = first.width or 155.0
        height = first.height or 60.0
        return {
            "x": left + max(0.0, (right - left - width) / 2.0),
            "y": first.y,
            "width": width,
            "height": height,
        }

    def _build_operations(
        self,
        request: ChangeRequest,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if request.operation == "insert_task_after":
            return self._insert_task_after(request, context)
        if request.operation == "insert_task_before":
            return self._insert_task_before(request, context)
        if request.operation == "rename_element":
            return self._rename_element(request, context)
        if request.operation == "remove_element":
            return self._remove_element(request, context)
        return {
            "operations": [],
            "acceptance_criteria": [],
            "risks": [],
            "assumptions": [],
            "clarification_questions": ["This operation is not supported yet."],
        }

    def _insert_task_after(
        self,
        request: ChangeRequest,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        element = context["element"]
        outgoing_flows = context["outgoing_sequence_flows"]
        risks: list[str] = []

        lane_id, lane_name, lane_error = self._resolve_insertion_lane(
            element["process_id"],
            request.target_lane_name,
            element.get("lane_id"),
            element.get("lane_name"),
        )
        if lane_error:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": [],
                "assumptions": [],
                "clarification_questions": [lane_error],
            }
        task_type, type_error = self._resolve_new_task_type(request)
        if type_error:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": [],
                "assumptions": [],
                "clarification_questions": [type_error],
            }

        if len(outgoing_flows) > 1:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": ["The target has several outgoing branches."],
                "assumptions": [],
                "clarification_questions": [
                    "Which outgoing branch should contain the new task? Supply the sequence-flow ID."
                ],
            }

        operations = [
            PlannedOperation(
                id="op_001",
                operation="add_task",
                parameters={
                    "new_element_id": "${new_task_id}",
                    "name": request.new_name,
                    "process_id": element["process_id"],
                    "lane_id": lane_id,
                    "lane_name": lane_name,
                    "bpmn_type": task_type,
                },
                rationale="Create the requested task in the target process and actor lane.",
            )
        ]

        if outgoing_flows:
            original_flow = outgoing_flows[0]
            operations.extend(
                [
                    PlannedOperation(
                        id="op_002",
                        operation="remove_sequence_flow",
                        parameters={"sequence_flow_id": original_flow["id"]},
                        rationale="Temporarily detach the target from its current successor.",
                    ),
                    PlannedOperation(
                        id="op_003",
                        operation="add_sequence_flow",
                        parameters={
                            "new_sequence_flow_id": "${new_flow_1_id}",
                            "source_ref": element["id"],
                            "target_ref": "${new_task_id}",
                            "process_id": element["process_id"],
                        },
                        rationale="Connect the existing target to the new task.",
                    ),
                    PlannedOperation(
                        id="op_004",
                        operation="add_sequence_flow",
                        parameters={
                            "new_sequence_flow_id": "${new_flow_2_id}",
                            "source_ref": "${new_task_id}",
                            "target_ref": original_flow["target_ref"],
                            "process_id": element["process_id"],
                            "preserve_name": original_flow.get("name"),
                            "preserve_condition_expression": original_flow.get(
                                "condition_expression"
                            ),
                        },
                        rationale="Reconnect the new task to the original successor.",
                    ),
                ]
            )
        else:
            operations.append(
                PlannedOperation(
                    id="op_002",
                    operation="add_sequence_flow",
                    parameters={
                        "new_sequence_flow_id": "${new_flow_1_id}",
                        "source_ref": element["id"],
                        "target_ref": "${new_task_id}",
                        "process_id": element["process_id"],
                    },
                    rationale="Append the new task after the current implicit process exit.",
                )
            )
            risks.append("The new task will become the process's implicit exit node.")

        return {
            "operations": operations,
            "acceptance_criteria": [
                f"The new task {request.new_name!r} is directly reachable after {element['id']!r}.",
                "The original downstream path remains reachable.",
                "No sequence flow references an unknown element.",
                "The modified process has at least one reachable exit.",
                "All unaffected process variants remain unchanged.",
            ],
            "risks": risks,
            "assumptions": [
                "The new task uses the requested lane when provided; otherwise it inherits the anchor lane.",
                "Diagram coordinates are generated in the resolved destination lane.",
            ],
            "clarification_questions": [],
        }

    def _insert_task_before(
        self,
        request: ChangeRequest,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        element = context["element"]
        incoming_flows = context["incoming_sequence_flows"]
        risks: list[str] = []

        lane_id, lane_name, lane_error = self._resolve_insertion_lane(
            element["process_id"],
            request.target_lane_name,
            element.get("lane_id"),
            element.get("lane_name"),
        )
        if lane_error:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": [],
                "assumptions": [],
                "clarification_questions": [lane_error],
            }
        task_type, type_error = self._resolve_new_task_type(request)
        if type_error:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": [],
                "assumptions": [],
                "clarification_questions": [type_error],
            }

        if len(incoming_flows) > 1:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": ["The target has several incoming branches."],
                "assumptions": [],
                "clarification_questions": [
                    "Which incoming branch should contain the new task? Supply the sequence-flow ID."
                ],
            }

        operations = [
            PlannedOperation(
                id="op_001",
                operation="add_task",
                parameters={
                    "new_element_id": "${new_task_id}",
                    "name": request.new_name,
                    "process_id": element["process_id"],
                    "lane_id": lane_id,
                    "lane_name": lane_name,
                    "bpmn_type": task_type,
                },
                rationale="Create the requested task in the target process and actor lane.",
            )
        ]

        if incoming_flows:
            original_flow = incoming_flows[0]
            operations.extend(
                [
                    PlannedOperation(
                        id="op_002",
                        operation="remove_sequence_flow",
                        parameters={"sequence_flow_id": original_flow["id"]},
                        rationale="Temporarily detach the target from its current predecessor.",
                    ),
                    PlannedOperation(
                        id="op_003",
                        operation="add_sequence_flow",
                        parameters={
                            "new_sequence_flow_id": "${new_flow_1_id}",
                            "source_ref": original_flow["source_ref"],
                            "target_ref": "${new_task_id}",
                            "process_id": element["process_id"],
                            "preserve_name": original_flow.get("name"),
                            "preserve_condition_expression": original_flow.get(
                                "condition_expression"
                            ),
                        },
                        rationale="Connect the original predecessor to the new task.",
                    ),
                    PlannedOperation(
                        id="op_004",
                        operation="add_sequence_flow",
                        parameters={
                            "new_sequence_flow_id": "${new_flow_2_id}",
                            "source_ref": "${new_task_id}",
                            "target_ref": element["id"],
                            "process_id": element["process_id"],
                        },
                        rationale="Connect the new task to the original target.",
                    ),
                ]
            )
        else:
            operations.append(
                PlannedOperation(
                    id="op_002",
                    operation="add_sequence_flow",
                    parameters={
                        "new_sequence_flow_id": "${new_flow_1_id}",
                        "source_ref": "${new_task_id}",
                        "target_ref": element["id"],
                        "process_id": element["process_id"],
                    },
                    rationale="Prepend the new task before the current implicit process entry.",
                )
            )
            risks.append("The new task will become the process's implicit entry node.")

        return {
            "operations": operations,
            "acceptance_criteria": [
                f"The new task {request.new_name!r} is directly before {element['id']!r}.",
                "The original upstream and downstream paths remain reachable.",
                "No sequence flow references an unknown element.",
                "All unaffected process variants remain unchanged.",
            ],
            "risks": risks,
            "assumptions": [
                "The new task uses the requested lane when provided; otherwise it inherits the anchor lane.",
                "Diagram coordinates are generated in the resolved destination lane.",
            ],
            "clarification_questions": [],
        }

    @staticmethod
    def _rename_element(
        request: ChangeRequest,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        element = context["element"]
        return {
            "operations": [
                PlannedOperation(
                    id="op_001",
                    operation="rename_element",
                    parameters={
                        "element_id": element["id"],
                        "old_name": element.get("name"),
                        "new_name": request.new_name,
                    },
                    rationale="Change only the visible BPMN label of the selected element.",
                )
            ],
            "acceptance_criteria": [
                f"Element {element['id']!r} has the name {request.new_name!r}.",
                "Its BPMN type, process, lane, incoming flows, and outgoing flows are unchanged.",
                "No other same-named element in another process variant is renamed.",
            ],
            "risks": [],
            "assumptions": [],
            "clarification_questions": [],
        }

    @staticmethod
    def _remove_element(
        request: ChangeRequest,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del request
        element = context["element"]
        incoming_flows = context["incoming_sequence_flows"]
        outgoing_flows = context["outgoing_sequence_flows"]

        if element["type"] in {
            "startEvent",
            "endEvent",
            "exclusiveGateway",
            "inclusiveGateway",
            "parallelGateway",
            "complexGateway",
            "eventBasedGateway",
        }:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": ["Removing events or gateways may change control-flow semantics."],
                "assumptions": [],
                "clarification_questions": [
                    "Removal of events and gateways is not supported in this safe planning milestone."
                ],
            }

        if len(incoming_flows) != 1 or len(outgoing_flows) != 1:
            return {
                "operations": [],
                "acceptance_criteria": [],
                "risks": [
                    "The selected element is not a simple one-predecessor/one-successor node."
                ],
                "assumptions": [],
                "clarification_questions": [
                    "Removal is currently allowed only for an element with exactly one incoming "
                    "and one outgoing sequence flow."
                ],
            }

        incoming_flow = incoming_flows[0]
        outgoing_flow = outgoing_flows[0]
        operations = [
            PlannedOperation(
                id="op_001",
                operation="remove_sequence_flow",
                parameters={"sequence_flow_id": incoming_flow["id"]},
                rationale="Detach the selected element from its predecessor.",
            ),
            PlannedOperation(
                id="op_002",
                operation="remove_sequence_flow",
                parameters={"sequence_flow_id": outgoing_flow["id"]},
                rationale="Detach the selected element from its successor.",
            ),
            PlannedOperation(
                id="op_003",
                operation="remove_element",
                parameters={"element_id": element["id"]},
                rationale="Remove the selected simple flow node.",
            ),
            PlannedOperation(
                id="op_004",
                operation="add_sequence_flow",
                parameters={
                    "new_sequence_flow_id": "${new_flow_1_id}",
                    "source_ref": incoming_flow["source_ref"],
                    "target_ref": outgoing_flow["target_ref"],
                    "process_id": element["process_id"],
                },
                rationale="Reconnect the predecessor directly to the successor.",
            ),
        ]
        return {
            "operations": operations,
            "acceptance_criteria": [
                f"Element {element['id']!r} no longer exists.",
                "Its former predecessor connects directly to its former successor.",
                "The process remains structurally valid and its exit remains reachable.",
                "All unaffected process variants remain unchanged.",
            ],
            "risks": [
                "Any documentation or data associations attached to the removed element must be reviewed."
            ],
            "assumptions": [
                "The incoming and outgoing sequence flows carry no incompatible branch semantics."
            ],
            "clarification_questions": [],
        }
