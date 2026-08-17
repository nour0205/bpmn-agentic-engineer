import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.cli import build_parser
from bpmn_agentic_engineer.preview import (
    _presentation_suppressed_participants,
    generate_preview,
    semantic_diff,
)

FIXTURE = Path(__file__).parent / "fixtures" / "execution_process.bpmn"
ROOT = Path(__file__).parents[1]
DEMO_BEFORE = ROOT / "outputs" / "linkedin_demo" / "input" / "as_is.bpmn"
DEMO_AFTER = ROOT / "outputs" / "linkedin_demo" / "input" / "generated" / "as_is_v003.bpmn"


def changed_copy(tmp_path: Path, *, rename=False, add=False, remove=False) -> Path:
    tree = ET.parse(FIXTURE)
    root = tree.getroot()
    nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"task", "userTask"}]
    if rename:
        nodes[0].set("name", "A deterministic new name")
    if remove:
        victim = nodes[-1]
        for parent in root.iter():
            if victim in list(parent):
                parent.remove(victim)
                break
    if add:
        process = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "process")
        ET.SubElement(process, "{http://www.omg.org/spec/BPMN/20100524/MODEL}userTask", id="Preview_Added", name="Preview added task")
    target = tmp_path / "after.bpmn"
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


@pytest.mark.parametrize(("option", "key"), [("rename", "renamed_elements"), ("add", "added_elements"), ("remove", "removed_elements")])
def test_semantic_diff_element_changes(tmp_path: Path, option: str, key: str) -> None:
    after = changed_copy(tmp_path, **{option: True})
    assert semantic_diff(BpmnDocument(FIXTURE), BpmnDocument(after))[key]


def test_semantic_diff_detects_sequence_flow_change(tmp_path: Path) -> None:
    tree = ET.parse(FIXTURE)
    flow = next(node for node in tree.getroot().iter() if node.tag.rsplit("}", 1)[-1] == "sequenceFlow")
    flow.set("targetRef", flow.get("sourceRef"))
    after = tmp_path / "flow.bpmn"
    tree.write(after, encoding="utf-8", xml_declaration=True)
    diff = semantic_diff(BpmnDocument(FIXTURE), BpmnDocument(after))
    assert diff["added_sequence_flows"] and diff["removed_sequence_flows"]


def test_generate_preview_embeds_xml_summary_does_not_open_or_modify(monkeypatch, tmp_path: Path) -> None:
    after = changed_copy(tmp_path, rename=True, add=True)
    before_bytes, after_bytes = FIXTURE.read_bytes(), after.read_bytes()
    opened = []
    monkeypatch.setattr("bpmn_agentic_engineer.preview.webbrowser.open", opened.append)
    output, diff = generate_preview(FIXTURE, after, tmp_path / "preview.html", open_browser=False)
    page = output.read_text(encoding="utf-8")
    assert "beforeXml=" in page and "afterXml=" in page
    assert "A deterministic new name" in page and "Preview added task" in page
    assert diff["renamed_elements"] and diff["added_elements"]
    assert opened == []
    assert FIXTURE.read_bytes() == before_bytes and after.read_bytes() == after_bytes


def test_presentation_cli_parsing() -> None:
    args = build_parser().parse_args(["preview", "before.bpmn", "after.bpmn", "--presentation", "--no-open"])
    assert args.presentation and args.no_open


def test_presentation_html_is_focused_and_keeps_technical_diff(monkeypatch, tmp_path: Path) -> None:
    before_bytes, after_bytes = DEMO_BEFORE.read_bytes(), DEMO_AFTER.read_bytes()
    opened = []
    monkeypatch.setattr("bpmn_agentic_engineer.preview.webbrowser.open", opened.append)
    output, diff = generate_preview(DEMO_BEFORE, DEMO_AFTER, tmp_path / "presentation.html",
                                    presentation=True, open_browser=False)
    page = output.read_text(encoding="utf-8")
    assert "AI-ASSISTED BPMN TRANSFORMATION" in page
    assert ">AS-IS " in page and ">TO-BE " in page
    assert "Focused changes" in page and "Full process" in page
    assert ".diagrams{display:grid;grid-template-columns:1fr" in page
    assert ".canvas{height:320px}" in page
    assert "font-size:11px!important;font-weight:400!important" in page
    assert "<details><summary>Technical BPMN diff" in page
    assert "ADDED FLOW" in page and "REMOVED FLOW" in page
    assert "canvas.addMarker" in page
    for item in diff["added_elements"] + diff["removed_elements"]:
        assert item["id"] in page
    assert "OPTIMIZATION SUMMARY · 3 STRUCTURAL CHANGES" in page
    assert "Structural validation: 0 errors" in page
    assert opened == []
    assert DEMO_BEFORE.read_bytes() == before_bytes
    assert DEMO_AFTER.read_bytes() == after_bytes


def test_normal_preview_remains_technical(tmp_path: Path) -> None:
    output, _ = generate_preview(DEMO_BEFORE, DEMO_AFTER, tmp_path / "technical.html",
                                 presentation=False, open_browser=False)
    page = output.read_text(encoding="utf-8")
    assert "CHANGE SUMMARY" in page and "BEFORE" in page and "AFTER" in page
    assert "OPTIMIZATION SUMMARY" not in page
    assert "suppressPresentationChrome" not in page


def test_presentation_suppresses_only_generic_empty_participant(tmp_path: Path) -> None:
    before = BpmnDocument(DEMO_BEFORE)
    suppressed = _presentation_suppressed_participants(before)
    assert suppressed == ["Id_8fa9827e-f37c-44b7-9c0d-3c817e06ccee"]
    assert "Id_7c073926-c12a-4876-9e2d-d47048e5405e" not in suppressed

    output, _ = generate_preview(
        DEMO_BEFORE,
        DEMO_AFTER,
        tmp_path / "presentation.html",
        presentation=True,
        open_browser=False,
    )
    page = output.read_text(encoding="utf-8")
    assert 'suppressed={before:["Id_8fa9827e-f37c-44b7-9c0d-3c817e06ccee"]' in page
    assert "suppressPresentationChrome" in page
    assert "Direction d'Approvisionnement" in page
    assert "Direction Financiére" in page
