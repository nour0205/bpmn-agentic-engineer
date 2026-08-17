from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bpmn_agentic_engineer.bpmn import BpmnDocument, ProcessInspector
from bpmn_agentic_engineer.planning import ChangePlanner


SIMPLE = Path(__file__).parent / "fixtures" / "simple_process.bpmn"
AMBIGUOUS = Path(__file__).parent / "fixtures" / "ambiguous_processes.bpmn"


class PlanningTests(unittest.TestCase):
    def test_plans_task_insertion_after_unique_target(self) -> None:
        document = BpmnDocument(SIMPLE)
        plan = ChangePlanner(document, ProcessInspector(document)).plan(
            'Add task "Review budget" after "Financial validation"'
        )

        self.assertEqual(plan["status"], "ready_for_approval")
        self.assertTrue(plan["requires_approval"])
        self.assertEqual(plan["selected_target"]["id"], "Task_Finance")
        self.assertEqual(plan["planned_operations"][0]["operation"], "add_task")
        self.assertEqual(len(plan["planned_operations"]), 4)

    def test_plans_rename(self) -> None:
        document = BpmnDocument(SIMPLE)
        plan = ChangePlanner(document).plan(
            'Rename "Financial validation" to "Validate available budget"'
        )

        self.assertEqual(plan["status"], "ready_for_approval")
        self.assertEqual(plan["planned_operations"][0]["operation"], "rename_element")
        self.assertEqual(
            plan["planned_operations"][0]["parameters"]["new_name"],
            "Validate available budget",
        )

    def test_requires_clarification_for_duplicate_exact_names(self) -> None:
        document = BpmnDocument(AMBIGUOUS)
        plan = ChangePlanner(document).plan(
            'Rename "Review request" to "Validate request"'
        )

        self.assertEqual(plan["status"], "requires_clarification")
        self.assertEqual(len(plan["candidate_matches"]), 2)
        self.assertFalse(plan["requires_approval"])

    def test_process_filter_resolves_duplicate_name(self) -> None:
        document = BpmnDocument(AMBIGUOUS)
        plan = ChangePlanner(document).plan(
            'Rename "Review request" to "Validate request"',
            process_id="Process_B",
        )

        self.assertEqual(plan["status"], "ready_for_approval")
        self.assertEqual(plan["selected_target"]["id"], "Task_B")

    def test_missing_new_name_requires_clarification(self) -> None:
        document = BpmnDocument(SIMPLE)
        plan = ChangePlanner(document).plan(
            "Add a task after Financial validation",
            target_query="Financial validation",
        )

        self.assertEqual(plan["status"], "requires_clarification")
        self.assertTrue(
            any("new task" in question.lower() for question in plan["clarification_questions"])
        )


if __name__ == "__main__":
    unittest.main()
