from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import shutil
import tempfile
from typing import Any
import uuid
import xml.etree.ElementTree as ET

from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.bpmn.document import local_name
from bpmn_agentic_engineer.integrity import (
    compute_plan_checksum,
    sha256_file,
    verify_plan_checksum,
)
from bpmn_agentic_engineer.validation import BasicValidator


BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"


class BpmnPlanExecutor:
    """Execute an approved deterministic plan on a new BPMN file.

    The source file is never overwritten. The output is committed only after
    structural validation succeeds.
    """

    def execute(
        self,
        plan: dict[str, Any],
        output_path: str | Path,
        *,
        approved: bool,
    ) -> dict[str, Any]:
        if not approved:
            raise ValueError("Execution requires explicit approval.")
        if plan.get("status") != "ready_for_approval":
            raise ValueError("Only a plan with status 'ready_for_approval' can be executed.")
        if not verify_plan_checksum(plan):
            raise ValueError("Plan checksum is missing or invalid; regenerate the plan.")

        source_path = Path(str(plan.get("file", ""))).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source BPMN file not found: {source_path}")

        expected_source_hash = plan.get("source_sha256")
        current_source_hash = sha256_file(source_path)
        if expected_source_hash != current_source_hash:
            raise ValueError(
                "The source BPMN changed after planning. Generate and approve a new plan."
            )

        destination = Path(output_path).expanduser().resolve()
        if destination == source_path:
            raise ValueError("The output path must be different from the source BPMN path.")
        if destination.exists():
            raise FileExistsError(
                f"Output file already exists: {destination}. Choose a new path."
            )
        if destination.suffix.lower() not in {".bpmn", ".xml"}:
            raise ValueError("The output file must use a .bpmn or .xml extension.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._register_namespaces(source_path)

        before = BpmnDocument(source_path)
        temp_path: Path | None = None
        resolved_operations: list[dict[str, Any]] = []

        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}.",
                suffix=destination.suffix,
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)

            shutil.copy2(source_path, temp_path)
            tree = ET.parse(temp_path)
            root = tree.getroot()

            placeholder_values = self._resolve_placeholders(plan, root)
            resolved_operations = self._substitute_operations(
                plan.get("planned_operations", []),
                placeholder_values,
            )

            self._apply_operations(root, plan, resolved_operations)
            ET.indent(tree, space="  ")
            tree.write(temp_path, encoding="utf-8", xml_declaration=True)

            validation = BasicValidator(BpmnDocument(temp_path)).validate()
            if not validation["valid_for_agentic_editing"]:
                return {
                    "status": "execution_rolled_back",
                    "source_file": str(source_path),
                    "output_file": None,
                    "source_file_unchanged": sha256_file(source_path)
                    == expected_source_hash,
                    "applied_operations": 0,
                    "validation": validation,
                    "reason": "The generated BPMN failed structural validation.",
                }

            after = BpmnDocument(temp_path)
            diff = self._diff(before, after)
            os.replace(temp_path, destination)
            temp_path = None

            source_unchanged = sha256_file(source_path) == expected_source_hash
            if not source_unchanged:
                destination.unlink(missing_ok=True)
                raise RuntimeError("The source BPMN changed during execution; output was removed.")

            return {
                "status": "execution_succeeded",
                "source_file": str(source_path),
                "output_file": str(destination),
                "source_file_unchanged": True,
                "plan_checksum": plan["plan_checksum"],
                "executed_plan_checksum": compute_plan_checksum(plan),
                "applied_operations": len(resolved_operations),
                "resolved_placeholders": placeholder_values,
                "validation": validation,
                "diff": diff,
            }
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _register_namespaces(path: Path) -> None:
        seen: set[tuple[str, str]] = set()
        for _, namespace in ET.iterparse(path, events=("start-ns",)):
            prefix, uri = namespace
            pair = (prefix or "", uri)
            if pair in seen:
                continue
            seen.add(pair)
            try:
                ET.register_namespace(prefix or "", uri)
            except ValueError:
                # Reserved/generated prefixes do not need to be preserved.
                continue

    @staticmethod
    def _new_id(existing_ids: set[str]) -> str:
        while True:
            candidate = f"Id_{uuid.uuid4()}"
            if candidate not in existing_ids:
                existing_ids.add(candidate)
                return candidate

    def _resolve_placeholders(
        self,
        plan: dict[str, Any],
        root: ET.Element,
    ) -> dict[str, str]:
        existing_ids = {
            element.attrib["id"]
            for element in root.iter()
            if element.attrib.get("id")
        }
        placeholders: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                placeholders.add(value)
            elif isinstance(value, dict):
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)

        collect(plan.get("planned_operations", []))
        return {
            placeholder: self._new_id(existing_ids)
            for placeholder in sorted(placeholders)
        }

    @staticmethod
    def _substitute_operations(
        operations: list[dict[str, Any]],
        placeholders: dict[str, str],
    ) -> list[dict[str, Any]]:
        def substitute(value: Any) -> Any:
            if isinstance(value, str):
                return placeholders.get(value, value)
            if isinstance(value, dict):
                return {key: substitute(item) for key, item in value.items()}
            if isinstance(value, list):
                return [substitute(item) for item in value]
            return value

        return [substitute(deepcopy(operation)) for operation in operations]

    def _apply_operations(
        self,
        root: ET.Element,
        plan: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> None:
        for operation in operations:
            operation_name = operation.get("operation")
            parameters = operation.get("parameters", {})

            if operation_name == "add_task":
                self._add_task(root, parameters)
            elif operation_name == "remove_sequence_flow":
                self._remove_sequence_flow(root, parameters["sequence_flow_id"])
            elif operation_name == "add_sequence_flow":
                self._add_sequence_flow(root, parameters)
            elif operation_name == "rename_element":
                self._rename_element(root, parameters)
            elif operation_name == "remove_element":
                self._remove_element(root, parameters["element_id"])
            else:
                raise ValueError(f"Unsupported execution operation: {operation_name!r}")

        self._update_diagram(root, plan, operations)

    @staticmethod
    def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
        return {child: parent for parent in root.iter() for child in parent}

    @staticmethod
    def _find_by_id(root: ET.Element, identifier: str) -> ET.Element | None:
        return next(
            (element for element in root.iter() if element.attrib.get("id") == identifier),
            None,
        )

    @staticmethod
    def _find_process(root: ET.Element, process_id: str) -> ET.Element:
        process = next(
            (
                element
                for element in root.iter()
                if local_name(element.tag) == "process"
                and element.attrib.get("id") == process_id
            ),
            None,
        )
        if process is None:
            raise KeyError(f"Unknown BPMN process: {process_id}")
        return process

    @staticmethod
    def _model_tag(root: ET.Element, local: str) -> str:
        namespace = (
            root.tag.split("}", 1)[0][1:]
            if root.tag.startswith("{")
            else BPMN_MODEL_NS
        )
        return f"{{{namespace}}}{local}"

    def _add_task(self, root: ET.Element, parameters: dict[str, Any]) -> None:
        process = self._find_process(root, parameters["process_id"])
        task_type = str(parameters.get("bpmn_type") or "task")
        if task_type not in {
            "task",
            "userTask",
            "manualTask",
            "serviceTask",
            "sendTask",
            "receiveTask",
            "scriptTask",
            "businessRuleTask",
        }:
            raise ValueError(f"Unsupported new task type: {task_type}")

        attributes = {"id": parameters["new_element_id"]}
        if parameters.get("name"):
            attributes["name"] = str(parameters["name"])
        task = ET.Element(self._model_tag(root, task_type), attributes)
        ET.SubElement(task, self._model_tag(root, "documentation"))
        process.append(task)

        lane_id = parameters.get("lane_id")
        if lane_id:
            lane = self._find_by_id(root, str(lane_id))
            if lane is not None:
                existing_refs = {
                    (child.text or "").strip()
                    for child in lane
                    if local_name(child.tag) == "flowNodeRef"
                }
                if parameters["new_element_id"] not in existing_refs:
                    reference = ET.Element(self._model_tag(root, "flowNodeRef"))
                    reference.text = parameters["new_element_id"]
                    lane.append(reference)

    def _remove_sequence_flow(self, root: ET.Element, flow_id: str) -> None:
        flow = self._find_by_id(root, flow_id)
        if flow is None or local_name(flow.tag) != "sequenceFlow":
            raise KeyError(f"Unknown BPMN sequence flow: {flow_id}")

        source_ref = flow.attrib.get("sourceRef")
        target_ref = flow.attrib.get("targetRef")
        parent = self._parent_map(root).get(flow)
        if parent is None:
            raise ValueError(f"Cannot remove sequence flow {flow_id!r}.")
        parent.remove(flow)

        if source_ref:
            self._remove_flow_reference(root, source_ref, "outgoing", flow_id)
        if target_ref:
            self._remove_flow_reference(root, target_ref, "incoming", flow_id)
        self._remove_diagram_element(root, flow_id, expected_local_name="BPMNEdge")

    def _add_sequence_flow(self, root: ET.Element, parameters: dict[str, Any]) -> None:
        process = self._find_process(root, parameters["process_id"])
        source_ref = str(parameters["source_ref"])
        target_ref = str(parameters["target_ref"])
        source = self._find_by_id(root, source_ref)
        target = self._find_by_id(root, target_ref)
        if source is None or target is None:
            raise KeyError(
                f"Cannot add sequence flow: unknown source or target ({source_ref}, {target_ref})."
            )

        attributes = {
            "id": str(parameters["new_sequence_flow_id"]),
            "sourceRef": source_ref,
            "targetRef": target_ref,
        }
        if parameters.get("preserve_name"):
            attributes["name"] = str(parameters["preserve_name"])
        flow = ET.Element(self._model_tag(root, "sequenceFlow"), attributes)
        ET.SubElement(flow, self._model_tag(root, "documentation"))
        condition = parameters.get("preserve_condition_expression")
        if condition:
            expression = ET.SubElement(flow, self._model_tag(root, "conditionExpression"))
            expression.text = str(condition)
        process.append(flow)

        self._append_flow_reference(root, source_ref, "outgoing", attributes["id"])
        self._append_flow_reference(root, target_ref, "incoming", attributes["id"])

    def _rename_element(self, root: ET.Element, parameters: dict[str, Any]) -> None:
        element = self._find_by_id(root, parameters["element_id"])
        if element is None:
            raise KeyError(f"Unknown BPMN element: {parameters['element_id']}")
        new_name = parameters.get("new_name")
        if new_name is None:
            element.attrib.pop("name", None)
        else:
            element.set("name", str(new_name))

    def _remove_element(self, root: ET.Element, element_id: str) -> None:
        element = self._find_by_id(root, element_id)
        if element is None:
            raise KeyError(f"Unknown BPMN element: {element_id}")

        # The approved plan normally removes connected sequence flows first.
        connected = [
            candidate.attrib["id"]
            for candidate in root.iter()
            if local_name(candidate.tag) == "sequenceFlow"
            and candidate.attrib.get("id")
            and (
                candidate.attrib.get("sourceRef") == element_id
                or candidate.attrib.get("targetRef") == element_id
            )
        ]
        if connected:
            raise ValueError(
                f"Element {element_id!r} still has connected sequence flows: {connected}."
            )

        parent_map = self._parent_map(root)
        for candidate in list(root.iter()):
            if local_name(candidate.tag) == "association" and (
                candidate.attrib.get("sourceRef") == element_id
                or candidate.attrib.get("targetRef") == element_id
            ):
                association_id = candidate.attrib.get("id")
                parent = parent_map.get(candidate)
                if parent is not None:
                    parent.remove(candidate)
                if association_id:
                    self._remove_diagram_element(
                        root, association_id, expected_local_name="BPMNEdge"
                    )

        parent = self._parent_map(root).get(element)
        if parent is None:
            raise ValueError(f"Cannot remove BPMN element {element_id!r}.")
        parent.remove(element)
        self._remove_diagram_element(root, element_id, expected_local_name="BPMNShape")

        for lane in root.iter():
            if local_name(lane.tag) != "lane":
                continue
            for child in list(lane):
                if local_name(child.tag) == "flowNodeRef" and (
                    child.text or ""
                ).strip() == element_id:
                    lane.remove(child)

    def _append_flow_reference(
        self,
        root: ET.Element,
        node_id: str,
        reference_type: str,
        flow_id: str,
    ) -> None:
        node = self._find_by_id(root, node_id)
        if node is None:
            raise KeyError(f"Unknown BPMN flow node: {node_id}")
        reference = ET.Element(self._model_tag(root, reference_type))
        reference.text = flow_id
        node.append(reference)

    def _remove_flow_reference(
        self,
        root: ET.Element,
        node_id: str,
        reference_type: str,
        flow_id: str,
    ) -> None:
        node = self._find_by_id(root, node_id)
        if node is None:
            return
        for child in list(node):
            if local_name(child.tag) == reference_type and (
                child.text or ""
            ).strip() == flow_id:
                node.remove(child)

    def _remove_diagram_element(
        self,
        root: ET.Element,
        bpmn_element_id: str,
        *,
        expected_local_name: str,
    ) -> None:
        parent_map = self._parent_map(root)
        for element in list(root.iter()):
            if (
                local_name(element.tag) == expected_local_name
                and element.attrib.get("bpmnElement") == bpmn_element_id
            ):
                parent = parent_map.get(element)
                if parent is not None:
                    parent.remove(element)

    def _update_diagram(
        self,
        root: ET.Element,
        plan: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> None:
        add_task_operations = [
            operation
            for operation in operations
            if operation.get("operation") == "add_task"
        ]
        for operation in add_task_operations:
            self._add_task_shape(root, plan, operation["parameters"], operations)

        for operation in operations:
            if operation.get("operation") == "add_sequence_flow":
                self._add_sequence_flow_edge(root, operation["parameters"])

    @staticmethod
    def _shape_for(root: ET.Element, bpmn_element_id: str) -> ET.Element | None:
        return next(
            (
                element
                for element in root.iter()
                if local_name(element.tag) == "BPMNShape"
                and element.attrib.get("bpmnElement") == bpmn_element_id
            ),
            None,
        )

    @staticmethod
    def _bounds_element(shape: ET.Element | None) -> ET.Element | None:
        if shape is None:
            return None
        return next(
            (child for child in shape if local_name(child.tag) == "Bounds"),
            None,
        )

    @staticmethod
    def _float_attribute(element: ET.Element, name: str, default: float = 0.0) -> float:
        try:
            return float(element.attrib.get(name, default))
        except (TypeError, ValueError):
            return default

    def _add_task_shape(
        self,
        root: ET.Element,
        plan: dict[str, Any],
        parameters: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> None:
        plane = next(
            (element for element in root.iter() if local_name(element.tag) == "BPMNPlane"),
            None,
        )
        if plane is None:
            return

        selected_target = plan.get("selected_target") or {}
        target_id = selected_target.get("id")
        target_shape = self._shape_for(root, str(target_id)) if target_id else None
        target_bounds = self._bounds_element(target_shape)
        if target_bounds is None:
            return

        target_x = self._float_attribute(target_bounds, "x")
        target_y = self._float_attribute(target_bounds, "y")
        target_width = self._float_attribute(target_bounds, "width", 155.0)
        target_height = self._float_attribute(target_bounds, "height", 60.0)
        new_id = str(parameters["new_element_id"])
        process_id = str(parameters["process_id"])
        gap = 40.0
        shift = target_width + gap

        new_flow_parameters = [
            operation.get("parameters", {})
            for operation in operations
            if operation.get("operation") == "add_sequence_flow"
        ]
        inserted_after = any(
            flow.get("source_ref") == target_id and flow.get("target_ref") == new_id
            for flow in new_flow_parameters
        )
        inserted_before = any(
            flow.get("source_ref") == new_id and flow.get("target_ref") == target_id
            for flow in new_flow_parameters
        )

        if inserted_before:
            threshold = target_x
            self._shift_diagram_region(root, process_id, threshold, shift)
            new_x = target_x
        else:
            successor_ids = [
                flow.get("target_ref")
                for flow in new_flow_parameters
                if flow.get("source_ref") == new_id
            ]
            successor_bounds = None
            for successor_id in successor_ids:
                successor_bounds = self._bounds_element(
                    self._shape_for(root, str(successor_id))
                )
                if successor_bounds is not None:
                    break
            threshold = (
                self._float_attribute(successor_bounds, "x")
                if successor_bounds is not None
                else target_x + target_width + gap
            )
            self._shift_diagram_region(root, process_id, threshold, shift)
            new_x = target_x + target_width + gap

        lane_id = parameters.get("lane_id")
        lane_bounds = self._bounds_element(
            self._shape_for(root, str(lane_id)) if lane_id else None
        )
        if lane_bounds is not None:
            lane_y = self._float_attribute(lane_bounds, "y")
            lane_height = self._float_attribute(lane_bounds, "height")
            new_y = lane_y + max(8.0, (lane_height - target_height) / 2.0)
        else:
            new_y = target_y

        shape = ET.Element(
            f"{{{BPMNDI_NS}}}BPMNShape",
            {
                "id": f"DiagramElement_{uuid.uuid4()}",
                "bpmnElement": new_id,
            },
        )
        ET.SubElement(
            shape,
            f"{{{DC_NS}}}Bounds",
            {
                "x": self._format_number(new_x),
                "y": self._format_number(new_y),
                "width": self._format_number(target_width),
                "height": self._format_number(target_height),
            },
        )
        plane.append(shape)

    def _shift_diagram_region(
        self,
        root: ET.Element,
        process_id: str,
        threshold_x: float,
        delta_x: float,
    ) -> None:
        participant_id = None
        for participant in root.iter():
            if (
                local_name(participant.tag) == "participant"
                and participant.attrib.get("processRef") == process_id
            ):
                participant_id = participant.attrib.get("id")
                break

        participant_bounds = self._bounds_element(
            self._shape_for(root, str(participant_id)) if participant_id else None
        )
        top = (
            self._float_attribute(participant_bounds, "y", float("-inf"))
            if participant_bounds is not None
            else float("-inf")
        )
        bottom = (
            top + self._float_attribute(participant_bounds, "height", float("inf"))
            if participant_bounds is not None
            else float("inf")
        )

        lane_ids = {
            lane.attrib.get("id")
            for process_element in root.iter()
            if local_name(process_element.tag) == "process"
            and process_element.attrib.get("id") == process_id
            for lane in process_element.iter()
            if local_name(lane.tag) == "lane" and lane.attrib.get("id")
        }

        for shape in root.iter():
            if local_name(shape.tag) != "BPMNShape":
                continue
            bpmn_element = shape.attrib.get("bpmnElement")
            bounds = self._bounds_element(shape)
            if bounds is None:
                continue
            x = self._float_attribute(bounds, "x")
            y = self._float_attribute(bounds, "y")
            height = self._float_attribute(bounds, "height")
            center_y = y + height / 2.0

            if bpmn_element == participant_id or bpmn_element in lane_ids:
                width = self._float_attribute(bounds, "width")
                bounds.set("width", self._format_number(width + delta_x))
                continue

            if top <= center_y <= bottom and x >= threshold_x - 0.01:
                bounds.set("x", self._format_number(x + delta_x))

        for edge in root.iter():
            if local_name(edge.tag) != "BPMNEdge":
                continue
            for waypoint in edge:
                if local_name(waypoint.tag) != "waypoint":
                    continue
                x = self._float_attribute(waypoint, "x")
                y = self._float_attribute(waypoint, "y")
                if top <= y <= bottom and x >= threshold_x - 0.01:
                    waypoint.set("x", self._format_number(x + delta_x))

    def _add_sequence_flow_edge(
        self,
        root: ET.Element,
        parameters: dict[str, Any],
    ) -> None:
        plane = next(
            (element for element in root.iter() if local_name(element.tag) == "BPMNPlane"),
            None,
        )
        if plane is None:
            return

        source_bounds = self._bounds_element(
            self._shape_for(root, str(parameters["source_ref"]))
        )
        target_bounds = self._bounds_element(
            self._shape_for(root, str(parameters["target_ref"]))
        )
        if source_bounds is None or target_bounds is None:
            return

        sx = self._float_attribute(source_bounds, "x")
        sy = self._float_attribute(source_bounds, "y")
        sw = self._float_attribute(source_bounds, "width")
        sh = self._float_attribute(source_bounds, "height")
        tx = self._float_attribute(target_bounds, "x")
        ty = self._float_attribute(target_bounds, "y")
        tw = self._float_attribute(target_bounds, "width")
        th = self._float_attribute(target_bounds, "height")

        if sx <= tx:
            start = (sx + sw, sy + sh / 2.0)
            end = (tx, ty + th / 2.0)
        else:
            start = (sx, sy + sh / 2.0)
            end = (tx + tw, ty + th / 2.0)

        edge = ET.Element(
            f"{{{BPMNDI_NS}}}BPMNEdge",
            {
                "id": f"DiagramElement_{uuid.uuid4()}",
                "bpmnElement": str(parameters["new_sequence_flow_id"]),
            },
        )
        for x, y in (start, end):
            ET.SubElement(
                edge,
                f"{{{DI_NS}}}waypoint",
                {"x": self._format_number(x), "y": self._format_number(y)},
            )
        plane.append(edge)

    @staticmethod
    def _format_number(value: float) -> str:
        rounded = round(value, 3)
        return str(int(rounded)) if rounded.is_integer() else str(rounded)

    @staticmethod
    def _diff(before: BpmnDocument, after: BpmnDocument) -> dict[str, Any]:
        before_element_ids = set(before.elements)
        after_element_ids = set(after.elements)
        before_flow_ids = set(before.sequence_flows)
        after_flow_ids = set(after.sequence_flows)

        renamed = []
        for element_id in sorted(before_element_ids & after_element_ids):
            old = before.elements[element_id]
            new = after.elements[element_id]
            if old.name != new.name:
                renamed.append(
                    {
                        "id": element_id,
                        "old_name": old.name,
                        "new_name": new.name,
                    }
                )

        return {
            "added_elements": [
                after.elements[element_id].to_dict()
                for element_id in sorted(after_element_ids - before_element_ids)
            ],
            "removed_elements": [
                before.elements[element_id].to_dict()
                for element_id in sorted(before_element_ids - after_element_ids)
            ],
            "renamed_elements": renamed,
            "added_sequence_flows": [
                after.sequence_flows[flow_id].to_dict()
                for flow_id in sorted(after_flow_ids - before_flow_ids)
            ],
            "removed_sequence_flows": [
                before.sequence_flows[flow_id].to_dict()
                for flow_id in sorted(before_flow_ids - after_flow_ids)
            ],
        }
