from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from bpmn_agentic_engineer.models import BpmnElement, SequenceFlow


FLOW_NODE_TYPES = {
    "startEvent",
    "endEvent",
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
    "task",
    "userTask",
    "manualTask",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "scriptTask",
    "businessRuleTask",
    "callActivity",
    "subProcess",
    "exclusiveGateway",
    "inclusiveGateway",
    "parallelGateway",
    "complexGateway",
    "eventBasedGateway",
}


def local_name(tag: str) -> str:
    """Return an XML local name, independent of namespace prefix."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def clean_label(value: str | None) -> str | None:
    """Normalize Bizagi labels while preserving their wording."""
    if value is None:
        return None
    cleaned = " ".join(value.replace("\u00a0", " ").split())
    return cleaned or None


@dataclass(frozen=True)
class DiagramBounds:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def contains_point(self, x: float, y: float, tolerance: float = 1.0) -> bool:
        return (
            self.x - tolerance <= x <= self.right + tolerance
            and self.y - tolerance <= y <= self.bottom + tolerance
        )

    def intersection_area(self, other: DiagramBounds) -> float:
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        return max(0.0, right - left) * max(0.0, bottom - top)


class BpmnDocument:
    """Read-only representation of a BPMN XML document.

    Lane assignment uses the standard ``flowNodeRef`` relation first. When a
    Bizagi export omits those references, it falls back to BPMN DI geometry:
    a flow node is assigned to the lane rectangle that contains its shape.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"BPMN file not found: {self.path}")
        if self.path.suffix.lower() not in {".bpmn", ".xml"}:
            raise ValueError("Expected a .bpmn or .xml file.")

        try:
            self.tree = ET.parse(self.path)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid XML: {exc}") from exc

        self.root = self.tree.getroot()
        self._raw_ids = [
            element.attrib["id"]
            for element in self.root.iter()
            if element.attrib.get("id")
        ]
        self.id_counts = Counter(self._raw_ids)

        self.processes: dict[str, dict[str, str | None]] = {}
        self.participants: dict[str, dict[str, str | None]] = {}
        self.participant_by_process: dict[str, str] = {}
        self.elements: dict[str, BpmnElement] = {}
        self.sequence_flows: dict[str, SequenceFlow] = {}
        self.lanes: dict[str, dict[str, str | None]] = {}
        self.lane_by_flow_node: dict[str, tuple[str, str | None]] = {}
        self.lane_assignment_source: dict[str, str] = {}
        self.shapes: dict[str, list[DiagramBounds]] = defaultdict(list)
        self.outgoing: dict[str, list[str]] = defaultdict(list)
        self.incoming: dict[str, list[str]] = defaultdict(list)

        self._extract()

    def _extract(self) -> None:
        self._extract_participants()
        self._extract_diagram_shapes()
        self._extract_processes()

        # Ensure graph dictionaries contain every known node.
        for element_id in self.elements:
            self.outgoing.setdefault(element_id, [])
            self.incoming.setdefault(element_id, [])

    def _extract_participants(self) -> None:
        for element in self.root.iter():
            if local_name(element.tag) != "participant":
                continue

            participant_id = element.attrib.get("id")
            if not participant_id:
                continue

            process_ref = element.attrib.get("processRef")
            participant = {
                "id": participant_id,
                "name": clean_label(element.attrib.get("name")),
                "process_ref": process_ref,
            }
            self.participants[participant_id] = participant

            if process_ref:
                self.participant_by_process[process_ref] = participant_id

    def _extract_diagram_shapes(self) -> None:
        for element in self.root.iter():
            if local_name(element.tag) != "BPMNShape":
                continue

            bpmn_element_id = element.attrib.get("bpmnElement")
            if not bpmn_element_id:
                continue

            for child in element:
                if local_name(child.tag) != "Bounds":
                    continue
                bounds = self._parse_bounds(child)
                if bounds is not None:
                    self.shapes[bpmn_element_id].append(bounds)
                break

    @staticmethod
    def _parse_bounds(element: ET.Element) -> DiagramBounds | None:
        try:
            return DiagramBounds(
                x=float(element.attrib["x"]),
                y=float(element.attrib["y"]),
                width=float(element.attrib["width"]),
                height=float(element.attrib["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _extract_processes(self) -> None:
        for process in self.root.iter():
            if local_name(process.tag) != "process":
                continue

            process_id = process.attrib.get("id")
            if not process_id:
                continue

            participant_id = self.participant_by_process.get(process_id)
            participant = self.participants.get(participant_id) if participant_id else None

            self.processes[process_id] = {
                "id": process_id,
                "name": clean_label(process.attrib.get("name")),
                "is_executable": process.attrib.get("isExecutable"),
                "participant_id": participant_id,
                "participant_name": participant.get("name") if participant else None,
            }

            explicit_lane_map = self._extract_lanes(process, process_id)
            self._extract_process_contents(process, process_id, explicit_lane_map)

    def _extract_lanes(
        self,
        process: ET.Element,
        process_id: str,
    ) -> dict[str, tuple[str, str | None]]:
        explicit_lane_map: dict[str, tuple[str, str | None]] = {}

        for descendant in process.iter():
            if local_name(descendant.tag) != "lane":
                continue

            lane_id = descendant.attrib.get("id")
            if not lane_id:
                continue

            lane_name = clean_label(descendant.attrib.get("name"))
            self.lanes[lane_id] = {
                "id": lane_id,
                "name": lane_name,
                "process_id": process_id,
            }

            for child in descendant:
                if local_name(child.tag) != "flowNodeRef" or not child.text:
                    continue
                flow_node_id = child.text.strip()
                explicit_lane_map[flow_node_id] = (lane_id, lane_name)
                self.lane_by_flow_node[flow_node_id] = (lane_id, lane_name)
                self.lane_assignment_source[flow_node_id] = "flowNodeRef"

        return explicit_lane_map

    def _extract_process_contents(
        self,
        process: ET.Element,
        process_id: str,
        explicit_lane_map: dict[str, tuple[str, str | None]],
    ) -> None:
        for descendant in process.iter():
            element_type = local_name(descendant.tag)
            element_id = descendant.attrib.get("id")
            if not element_id:
                continue

            if element_type == "sequenceFlow":
                self._extract_sequence_flow(descendant, process_id)
                continue

            if element_type not in FLOW_NODE_TYPES:
                continue

            lane_id: str | None
            lane_name: str | None
            lane_id, lane_name = explicit_lane_map.get(element_id, (None, None))

            if lane_id is None:
                geometry_lane = self._infer_lane_from_geometry(element_id, process_id)
                if geometry_lane is not None:
                    lane_id, lane_name = geometry_lane
                    self.lane_by_flow_node[element_id] = geometry_lane
                    self.lane_assignment_source[element_id] = "geometry"

            self.elements[element_id] = BpmnElement(
                id=element_id,
                type=element_type,
                name=clean_label(descendant.attrib.get("name")),
                process_id=process_id,
                lane_id=lane_id,
                lane_name=lane_name,
            )

    def _extract_sequence_flow(self, element: ET.Element, process_id: str) -> None:
        flow_id = element.attrib.get("id")
        source_ref = element.attrib.get("sourceRef")
        target_ref = element.attrib.get("targetRef")
        if not flow_id or not source_ref or not target_ref:
            return

        condition = None
        for child in element:
            if local_name(child.tag) == "conditionExpression":
                condition = clean_label(child.text)
                break

        flow = SequenceFlow(
            id=flow_id,
            source_ref=source_ref,
            target_ref=target_ref,
            name=clean_label(element.attrib.get("name")),
            process_id=process_id,
            condition_expression=condition,
        )
        self.sequence_flows[flow_id] = flow
        self.outgoing[source_ref].append(target_ref)
        self.incoming[target_ref].append(source_ref)

    def _infer_lane_from_geometry(
        self,
        element_id: str,
        process_id: str,
    ) -> tuple[str, str | None] | None:
        node_shapes = self.shapes.get(element_id, [])
        if not node_shapes:
            return None

        lane_shapes: list[tuple[str, str | None, DiagramBounds]] = []
        for lane_id, lane in self.lanes.items():
            if lane.get("process_id") != process_id:
                continue
            lane_name = lane.get("name")
            for bounds in self.shapes.get(lane_id, []):
                lane_shapes.append((lane_id, lane_name, bounds))

        if not lane_shapes:
            return None

        # First choice: the node centre is inside the lane rectangle.
        centre_matches: list[tuple[float, float, str, str | None]] = []
        for node_bounds in node_shapes:
            center_x, center_y = node_bounds.center
            for lane_id, lane_name, lane_bounds in lane_shapes:
                if not lane_bounds.contains_point(center_x, center_y):
                    continue
                overlap = lane_bounds.intersection_area(node_bounds)
                centre_matches.append(
                    (-overlap, lane_bounds.area, lane_id, lane_name)
                )

        if centre_matches:
            centre_matches.sort(key=lambda item: (item[0], item[1], item[2]))
            _, _, lane_id, lane_name = centre_matches[0]
            return lane_id, lane_name

        # Fallback for shapes positioned on a lane border: choose the lane with
        # the largest overlap, but only when the overlap is meaningful.
        overlap_matches: list[tuple[float, float, str, str | None]] = []
        for node_bounds in node_shapes:
            if node_bounds.area <= 0:
                continue
            for lane_id, lane_name, lane_bounds in lane_shapes:
                overlap_ratio = lane_bounds.intersection_area(node_bounds) / node_bounds.area
                if overlap_ratio < 0.25:
                    continue
                overlap_matches.append(
                    (-overlap_ratio, lane_bounds.area, lane_id, lane_name)
                )

        if overlap_matches:
            overlap_matches.sort(key=lambda item: (item[0], item[1], item[2]))
            _, _, lane_id, lane_name = overlap_matches[0]
            return lane_id, lane_name

        return None

    def element(self, element_id: str) -> BpmnElement:
        try:
            return self.elements[element_id]
        except KeyError as exc:
            raise KeyError(f"Unknown BPMN flow node: {element_id}") from exc

    def duplicate_ids(self) -> list[str]:
        return sorted(
            identifier
            for identifier, count in self.id_counts.items()
            if count > 1
        )
