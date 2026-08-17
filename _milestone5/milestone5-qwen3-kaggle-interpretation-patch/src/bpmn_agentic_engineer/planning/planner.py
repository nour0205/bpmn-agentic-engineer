from __future__ import annotations

import re
from typing import Any

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
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
    ) -> ChangeRequest:
        if not request_text or not request_text.strip():
            raise ValueError("Change request cannot be empty.")

        normalized = normalize_text(request_text)
        quoted = _quoted_fragments(request_text)

        operation = "unsupported"
        position: str | None = None
        inferred_target: str | None = None
        inferred_new_name: str | None = None

        if any(keyword in normalized for keyword in ("renommer", "rename")):
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
    ) -> dict[str, Any]:
        request = self.parser.parse(
            request_text,
            operation_hint=operation,
            target_query=target_query,
            target_element_id=target_element_id,
            process_id=process_id,
            new_name=new_name,
            lane_name=lane_name,
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
                    "or remove a simple element.",
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

        grounding = self.grounder.ground(
            target_query=request.target_query,
            target_element_id=request.target_element_id,
            process_id=request.target_process_id,
            lane_name=request.target_lane_name,
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
    ) -> dict[str, Any]:
        result = self._plan_without_integrity(
            request_text,
            operation=operation,
            target_query=target_query,
            target_element_id=target_element_id,
            process_id=process_id,
            new_name=new_name,
            lane_name=lane_name,
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
        if not request.target_element_id and not request.target_query:
            questions.append("Which existing BPMN element should be changed?")
        if request.operation in {"insert_task_after", "insert_task_before", "insert_task"}:
            if not request.new_name:
                questions.append("What should the new task be called?")
            if request.operation == "insert_task":
                questions.append("Should the new task be inserted before or after the target?")
        if request.operation == "rename_element" and not request.new_name:
            questions.append("What should the new element name be?")
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
                    "lane_id": element["lane_id"],
                    "lane_name": element["lane_name"],
                    "bpmn_type": "task",
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
                "The new task inherits the target element's process and lane.",
                "Diagram coordinates will be generated during the later execution milestone.",
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
                    "lane_id": element["lane_id"],
                    "lane_name": element["lane_name"],
                    "bpmn_type": "task",
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
                "The new task inherits the target element's process and lane.",
                "Diagram coordinates will be generated during the later execution milestone.",
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
