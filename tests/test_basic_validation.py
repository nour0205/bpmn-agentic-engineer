from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.validation import BasicValidator


class BasicValidationTests(unittest.TestCase):
    def validate_process(self, body: str) -> dict:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <process id="Process_1">{body}</process>
</definitions>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "process.bpmn"
            path.write_text(xml, encoding="utf-8")
            return BasicValidator(BpmnDocument(path)).validate()

    def test_empty_process_is_an_info_container(self) -> None:
        result = self.validate_process("")

        self.assertEqual(result["error_count"], 0)
        self.assertEqual([issue["code"] for issue in result["issues"]], ["EMPTY_PROCESS_CONTAINER"])

    def test_implicit_start_reaches_explicit_end(self) -> None:
        result = self.validate_process("""
    <task id="Task_1" />
    <endEvent id="End_1" />
    <sequenceFlow id="Flow_1" sourceRef="Task_1" targetRef="End_1" />
""")
        issues = {issue["code"]: issue for issue in result["issues"]}

        self.assertEqual(result["error_count"], 0)
        self.assertEqual(issues["EXPLICIT_END_WITH_IMPLICIT_START"]["severity"], "warning")
        self.assertNotIn("MISSING_START_EVENT", issues)
        self.assertNotIn("NO_INCOMING_FLOW", issues)
        self.assertNotIn("UNREACHABLE_NODE", issues)

    def test_implicit_start_and_end_are_valid_boundaries(self) -> None:
        result = self.validate_process("""
    <task id="Task_1" />
    <task id="Task_2" />
    <sequenceFlow id="Flow_1" sourceRef="Task_1" targetRef="Task_2" />
""")
        codes = {issue["code"] for issue in result["issues"]}

        self.assertEqual(result["error_count"], 0)
        self.assertNotIn("MISSING_START_EVENT", codes)
        self.assertNotIn("MISSING_END_EVENT", codes)
        self.assertNotIn("NO_INCOMING_FLOW", codes)


if __name__ == "__main__":
    unittest.main()
