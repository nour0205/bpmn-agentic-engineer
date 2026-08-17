from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.validation import BasicValidator


FIXTURE = Path(__file__).parent / "fixtures" / "simple_process.bpmn"


class InspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = BpmnDocument(FIXTURE)
        self.inspector = ProcessInspector(self.document)

    def test_extracts_main_structure(self) -> None:
        summary = self.inspector.summary()
        self.assertEqual(summary["statistics"]["process_count"], 1)
        self.assertEqual(summary["statistics"]["flow_node_count"], 6)
        self.assertEqual(summary["statistics"]["sequence_flow_count"], 5)
        self.assertEqual(summary["statistics"]["lane_count"], 2)

    def test_finds_financial_task(self) -> None:
        matches = self.inspector.find_elements("financial validation")
        self.assertTrue(matches)
        self.assertEqual(matches[0]["id"], "Task_Finance")
        self.assertEqual(matches[0]["lane_name"], "Finance")

    def test_returns_context(self) -> None:
        context = self.inspector.element_context("Task_Finance")
        self.assertEqual(context["predecessors"][0]["id"], "Task_Submit")
        self.assertEqual(context["successors"][0]["id"], "Gateway_Approved")

    def test_finds_path(self) -> None:
        result = self.inspector.find_path("StartEvent_1", "EndEvent_1")
        self.assertTrue(result["found"])
        self.assertEqual(result["node_ids"][0], "StartEvent_1")
        self.assertEqual(result["node_ids"][-1], "EndEvent_1")

    def test_fixture_passes_basic_validation(self) -> None:
        result = BasicValidator(self.document).validate()
        self.assertTrue(result["valid_for_agentic_editing"])
        self.assertEqual(result["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
