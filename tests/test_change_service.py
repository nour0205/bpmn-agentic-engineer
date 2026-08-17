from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bpmn_agentic_engineer.change_service import BpmnChangeService, BpmnInteractiveSession
from bpmn_agentic_engineer.cli import _clarification_prompt


class FakeAgentService:
    def __init__(self, *, clarification: bool = False, remote_state: str = "complete"):
        self.clarification = clarification
        self.remote_state = remote_state
        self.run_id = "run_hidden"
        self.last_state: dict[str, Any] = {"run_id": self.run_id, "status": "received"}
        self.resume_calls: list[dict[str, Any]] = []

    def start(self, source, request, **kwargs):
        self.source = Path(source)
        self.request = request
        self.output = Path(kwargs["output_path"])
        self.last_state = {"run_id": self.run_id, "status": "waiting_for_llm"}
        return self.last_state

    def llm_status(self, run_id):
        assert run_id == self.run_id
        return {"state": self.remote_state, "raw": self.remote_state}

    def status(self, run_id):
        assert run_id == self.run_id
        return self.last_state

    def resume(self, run_id, **kwargs):
        assert run_id == self.run_id
        self.resume_calls.append(kwargs)
        if kwargs.get("fetch_llm"):
            if self.clarification:
                self.last_state = {
                    "run_id": self.run_id,
                    "status": "needs_clarification",
                    "llm_interpretation": {"requires_clarification": True},
                    "plan": {
                        "status": "requires_clarification",
                        "clarification_questions": ["Which activity?"],
                        "candidate_matches": [{"name": "Task A"}, {"name": "Task B"}],
                    },
                }
            else:
                self.last_state = self._approval_state()
            return self.last_state
        if "target_query" in kwargs:
            self.last_state = self._approval_state()
            return self.last_state
        if kwargs.get("approved") is True:
            self.output.write_text("<bpmn />", encoding="utf-8")
            self.last_state = {
                "run_id": self.run_id,
                "status": "completed",
                "llm_interpretation": {"operation": "rename_element"},
                "plan": self._approval_state()["plan"],
                "execution_result": {
                    "output_file": str(self.output),
                    "diff": {"renamed_elements": [{"old_name": "A", "new_name": "B"}]},
                },
                "validation": {"valid_for_agentic_editing": True, "error_count": 0},
            }
            return self.last_state
        self.last_state = {"run_id": self.run_id, "status": "cancelled"}
        return self.last_state

    def _approval_state(self):
        return {
            "run_id": self.run_id,
            "status": "waiting_for_approval",
            "llm_interpretation": {"operation": "rename_element"},
            "plan": {
                "status": "ready_for_approval",
                "selected_target": {"name": "A"},
                "planned_operations": [{"operation": "rename_element", "parameters": {}}],
            },
        }


def source_file(tmp_path: Path) -> Path:
    source = tmp_path / "process.bpmn"
    source.write_text("original", encoding="utf-8")
    return source


def service(fake: FakeAgentService) -> BpmnChangeService:
    return BpmnChangeService(
        agent_service=fake,
        poll_interval=0,
        sleep=lambda _seconds: None,
    )


def test_facade_fetches_approves_and_completes(tmp_path: Path) -> None:
    fake = FakeAgentService()
    result = service(fake).run_change(
        source_file(tmp_path),
        "Renommez A en B.",
        approval_handler=lambda _state: True,
    )
    assert result["status"] == "completed"
    assert Path(result["output_file"]).exists()
    assert fake.resume_calls[0] == {"fetch_llm": True}
    assert fake.resume_calls[1]["approved"] is True


def test_facade_clarifies_same_run_then_approves(tmp_path: Path) -> None:
    fake = FakeAgentService(clarification=True)
    result = service(fake).run_change(
        source_file(tmp_path),
        "Renommez l'activité liée au dossier.",
        clarification_handler=lambda _state: "Task B",
        approval_handler=lambda _state: True,
    )
    assert result["status"] == "completed"
    assert {"target_query": "Task B"} in fake.resume_calls
    assert fake.run_id == "run_hidden"


def test_facade_rejected_approval_cancels(tmp_path: Path) -> None:
    fake = FakeAgentService()
    result = service(fake).run_change(
        source_file(tmp_path),
        "Renommez A en B.",
        approval_handler=lambda _state: False,
    )
    assert result["status"] == "cancelled"
    assert result["output_file"] is None


def test_facade_reports_kaggle_failure(tmp_path: Path) -> None:
    fake = FakeAgentService(remote_state="failed")
    result = service(fake).run_change(source_file(tmp_path), "Renommez A en B.")
    assert result["status"] == "failed"
    assert "Kaggle interpretation failed" in result["error"]


def test_facade_never_overwrites_input(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    with pytest.raises(ValueError, match="different"):
        service(FakeAgentService()).run_change(
            source,
            "Renommez A en B.",
            output_file=source,
        )
    assert source.read_text(encoding="utf-8") == "original"


class CompletingFacade:
    def run_change(self, source_file, request, output_file=None, **kwargs):
        del kwargs
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(request, encoding="utf-8")
        return {
            "status": "completed",
            "source_file": str(source_file),
            "output_file": str(output),
            "validation": {"valid_for_agentic_editing": True},
        }


def test_interactive_session_chains_versions_and_resets(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    session = BpmnInteractiveSession(source, CompletingFacade())
    first = session.apply("first")
    second = session.apply("second")
    assert Path(first["output_file"]).name == "process_v001.bpmn"
    assert Path(second["output_file"]).name == "process_v002.bpmn"
    assert session.current.name == "process_v002.bpmn"
    session.reset()
    assert session.current == source.resolve()
    assert len(session.history) == 2


def test_unsupported_result_never_executes(tmp_path: Path) -> None:
    class Unsupported(FakeAgentService):
        def start(self, source, request, **kwargs):
            self.output = Path(kwargs["output_path"])
            return {
                "run_id": self.run_id,
                "status": "failed",
                "error": "This type of BPMN modification is not currently supported.",
            }

    output = tmp_path / "unsupported.bpmn"
    result = service(Unsupported()).run_change(
        source_file(tmp_path),
        "Optimisez ce processus.",
        output_file=output,
    )
    assert result["status"] == "failed"
    assert not output.exists()


def test_cli_clarification_resolves_explicit_candidate_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "Celle dans la lane « Responsable du Département Juridique ».",
    )
    answer = _clarification_prompt(
        {
            "plan": {
                "clarification_questions": ["Laquelle souhaitez-vous modifier ?"],
                "candidate_matches": [
                    {
                        "id": "Task_Legal",
                        "name": "Revoir et valider le contrat",
                        "lane_name": "Responsable du Département Juridique",
                    },
                    {
                        "id": "Task_Supply",
                        "name": "Revoir et valider le contrat",
                        "lane_name": "Direction d'Approvisionnement",
                    },
                ],
            }
        }
    )
    assert answer == {"target_element_id": "Task_Legal"}


def test_cli_clarification_tolerates_terminal_mojibake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "Celle dans la lane Responsable du DÃ©partement Juridique.",
    )
    answer = _clarification_prompt(
        {
            "plan": {
                "candidate_matches": [
                    {
                        "id": "Task_Legal",
                        "name": "Revoir et valider le contrat",
                        "lane_name": "Responsable du Département Juridique",
                    },
                    {
                        "id": "Task_Supply",
                        "name": "Revoir et valider le contrat",
                        "lane_name": "Direction d'Approvisionnement",
                    },
                ]
            }
        }
    )
    assert answer == {"target_element_id": "Task_Legal"}
