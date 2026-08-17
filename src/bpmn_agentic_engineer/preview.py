from __future__ import annotations

import html
import json
import re
import webbrowser
from collections import defaultdict
from pathlib import Path

from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.validation import BasicValidator


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _element_dict(element) -> dict:
    return element.to_dict()


def semantic_diff(before: BpmnDocument, after: BpmnDocument) -> dict[str, list[dict]]:
    """Compare two parsed BPMN documents without mutating either one."""
    common = set(before.elements) & set(after.elements)
    renamed = []
    lane_changes = []
    type_changes = []
    matched_before = set(common)
    matched_after = set(common)
    identity_after: dict[str, str] = {identifier: identifier for identifier in common}

    for identifier in sorted(common):
        old, new = before.elements[identifier], after.elements[identifier]
        if old.name != new.name:
            renamed.append({"id": identifier, "old_name": old.name, "new_name": new.name,
                            "old": _element_dict(old), "new": _element_dict(new)})
        if old.lane_name != new.lane_name:
            lane_changes.append({"id": identifier, "name": new.name or old.name,
                                 "old_lane": old.lane_name, "new_lane": new.lane_name})
        if old.type != new.type:
            type_changes.append({"id": identifier, "name": new.name or old.name,
                                 "old_type": old.type, "new_type": new.type})

    # Pair regenerated but semantically identical nodes deterministically.
    pools: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for identifier, element in after.elements.items():
        if identifier not in matched_after:
            pools[(_norm(element.name), element.type, _norm(element.lane_name))].append(identifier)
    for values in pools.values():
        values.sort(reverse=True)
    for identifier, element in sorted(before.elements.items()):
        if identifier in matched_before:
            continue
        key = (_norm(element.name), element.type, _norm(element.lane_name))
        if pools[key]:
            new_id = pools[key].pop()
            matched_before.add(identifier)
            matched_after.add(new_id)
            identity_after[new_id] = identifier

    added = [_element_dict(after.elements[i]) for i in sorted(set(after.elements) - matched_after)]
    removed = [_element_dict(before.elements[i]) for i in sorted(set(before.elements) - matched_before)]

    def flow_key(document: BpmnDocument, flow, *, after_side: bool) -> tuple:
        def node_key(identifier: str):
            if after_side and identifier in identity_after:
                return ("matched", identity_after[identifier])
            if not after_side and identifier in matched_before:
                return ("matched", identifier)
            element = document.elements.get(identifier)
            return ("semantic", _norm(element.name), element.type, _norm(element.lane_name)) if element else ("id", identifier)
        return (node_key(flow.source_ref), node_key(flow.target_ref), _norm(flow.name), _norm(flow.condition_expression))

    before_flows = defaultdict(list)
    after_flows = defaultdict(list)
    for flow in before.sequence_flows.values(): before_flows[flow_key(before, flow, after_side=False)].append(flow)
    for flow in after.sequence_flows.values(): after_flows[flow_key(after, flow, after_side=True)].append(flow)
    added_flows, removed_flows = [], []
    for key in sorted(set(before_flows) | set(after_flows), key=repr):
        old, new = before_flows[key], after_flows[key]
        removed_flows.extend(f.to_dict() for f in old[len(new):])
        added_flows.extend(f.to_dict() for f in new[len(old):])

    return {"added_elements": added, "removed_elements": removed, "renamed_elements": renamed,
            "added_sequence_flows": added_flows, "removed_sequence_flows": removed_flows,
            "lane_changes": lane_changes, "type_changes": type_changes}


def _json_for_script(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _label(item: dict, document: BpmnDocument) -> str:
    element = document.elements.get(item.get("id", ""))
    return (element.name if element else None) or item.get("name") or "Unnamed element"


def presentation_groups(before: BpmnDocument, after: BpmnDocument, diff: dict) -> list[dict]:
    """Conservatively group topology-proven changes for presentation."""
    added = {item["id"]: item for item in diff["added_elements"]}
    removed = {item["id"]: item for item in diff["removed_elements"]}
    used_added: set[str] = set()
    used_removed: set[str] = set()
    groups: list[dict] = []

    for start in sorted(removed):
        if any(node in removed for node in before.incoming[start]):
            continue
        chain = [start]
        while len(before.outgoing[chain[-1]]) == 1:
            nxt = before.outgoing[chain[-1]][0]
            if nxt not in removed or len(before.incoming[nxt]) != 1:
                break
            chain.append(nxt)
        if len(chain) < 2:
            continue
        incoming = [node for node in before.incoming[start] if node not in removed]
        outgoing = [node for node in before.outgoing[chain[-1]] if node not in removed]
        if len(incoming) != 1 or len(outgoing) != 1:
            continue
        predecessor, successor = incoming[0], outgoing[0]
        path, current = [], predecessor
        while len(after.outgoing[current]) == 1 and len(path) <= len(added):
            current = after.outgoing[current][0]
            if current == successor:
                break
            if current not in added or len(after.incoming[current]) != 1:
                path = []
                break
            path.append(current)
        services = [node for node in path if added[node].get("type") == "serviceTask"]
        if current == successor and len(services) == 1:
            service = services[0]
            groups.append({"code": "AUTOMATION", "removed": [removed[node] for node in chain],
                           "added": added[service]})
            used_removed.update(chain)
            used_added.add(service)

    before_edges = {(flow.source_ref, flow.target_ref) for flow in before.sequence_flows.values()}
    after_edges = {(flow.source_ref, flow.target_ref) for flow in after.sequence_flows.values()}
    for node in sorted(set(added) - used_added):
        incoming, outgoing = after.incoming[node], after.outgoing[node]
        if len(incoming) == len(outgoing) == 1:
            groups.append({"code": "PROCESS_CONTROL" if any(term in _norm(added[node].get("name")) for term in ("analys", "valid", "control")) else "ADDITION",
                           "element": added[node], "predecessor": incoming[0], "successor": outgoing[0],
                           "direct_before": (incoming[0], outgoing[0]) in before_edges})
            used_added.add(node)
    for node in sorted(set(removed) - used_removed):
        incoming, outgoing = before.incoming[node], before.outgoing[node]
        if len(incoming) == len(outgoing) == 1 and (incoming[0], outgoing[0]) in after_edges:
            groups.append({"code": "SIMPLIFICATION", "element": removed[node],
                           "predecessor": incoming[0], "successor": outgoing[0]})
            used_removed.add(node)
    for item in diff["renamed_elements"]:
        groups.append({"code": "RENAME", "element": item})
    for node in sorted(set(added) - used_added):
        groups.append({"code": "ADDITION", "element": added[node]})
    for node in sorted(set(removed) - used_removed):
        groups.append({"code": "REMOVAL", "element": removed[node]})
    return groups


def _presentation_summary(groups: list[dict], before: BpmnDocument, after: BpmnDocument) -> str:
    cards = []
    for index, group in enumerate(groups, 1):
        code = group["code"]
        if code == "AUTOMATION":
            old = "<br>→<br>".join(html.escape(item.get("name") or "Unnamed activity") for item in group["removed"])
            new = group["added"]
            title = "AUTOMATION"
            lead = f'{len(group["removed"])} human-oriented processing activities → 1 automated service task'
            body = f'<div class="before-list"><b>Removed</b><br>{old}</div><div class="after-list"><b>Added</b><br>{html.escape(new.get("name") or "Unnamed activity")}<small>{html.escape(new.get("lane_name") or "Unassigned lane")}</small></div>'
        elif code in {"PROCESS_CONTROL", "ADDITION"}:
            item = group["element"]
            title = "PROCESS CONTROL" if code == "PROCESS_CONTROL" else "ADDITION"
            lead = "Financial analysis added" if "analys" in _norm(item.get("name")) else "Activity added"
            body = f'<div class="after-list">{html.escape(item.get("name") or "Unnamed activity")}<small>Lane: {html.escape(item.get("lane_name") or "Unassigned")}</small></div>'
        elif code == "SIMPLIFICATION":
            item = group["element"]
            title, lead = "SIMPLIFICATION", "Intermediate activity removed and flow reconnected"
            body = f'<div class="before-list">{html.escape(item.get("name") or "Unnamed activity")}</div><small>New direct flow: {_node_label(group["predecessor"], before, after)} → {_node_label(group["successor"], before, after)}</small>'
        elif code == "RENAME":
            item = group["element"]
            title, lead = "LABEL CHANGE", "Activity renamed"
            body = f'{html.escape(item.get("old_name") or "Unnamed")} → {html.escape(item.get("new_name") or "Unnamed")}'
        else:
            item = group["element"]
            title, lead = "REMOVAL", "Activity removed"
            body = html.escape(item.get("name") or "Unnamed activity")
        cards.append(f'<article><div class="number">{index:02d}</div><div><h3>{title}</h3><strong>{lead}</strong>{body}</div></article>')
    return "".join(cards)


def _node_label(identifier: str, before: BpmnDocument, after: BpmnDocument) -> str:
    element = after.elements.get(identifier) or before.elements.get(identifier)
    return html.escape((element.name if element else None) or "Unnamed activity")


def _presentation_suppressed_participants(document: BpmnDocument) -> list[str]:
    """Return generic, empty participant IDs that are presentation-only chrome."""
    generic_names = {"processus principal", "main process"}
    process_node_counts = defaultdict(int)
    for element in document.elements.values():
        if element.process_id:
            process_node_counts[element.process_id] += 1
    return sorted(
        participant_id
        for participant_id, participant in document.participants.items()
        if _norm(participant.get("name")) in generic_names
        and not process_node_counts[participant.get("process_ref")]
    )


def generate_preview(before_path: str | Path, after_path: str | Path, output: str | Path | None = None,
                     *, title: str | None = None, open_browser: bool = True,
                     presentation: bool = False) -> tuple[Path, dict]:
    before, after = BpmnDocument(before_path), BpmnDocument(after_path)
    diff = semantic_diff(before, after)
    before_xml = before.path.read_text(encoding="utf-8-sig")
    after_xml = after.path.read_text(encoding="utf-8-sig")
    if output is None:
        safe = re.sub(r"[^\w.-]+", "_", after.path.stem, flags=re.UNICODE).strip("_")
        output = Path("outputs/previews") / f"{safe}_preview.html"
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    for heading, items, doc, css in (("ADDED", diff["added_elements"], after, "added"),
                                      ("REMOVED", diff["removed_elements"], before, "removed")):
        for item in items:
            lane = item.get("lane_name")
            detail = f"<small>Type: {html.escape(item.get('type') or '')}" + (f" · Lane: {html.escape(lane)}" if lane else "") + "</small>"
            sections.append(f'<li class="{css}"><b>{heading}</b><span>{html.escape(_label(item, doc))}</span>{detail}</li>')
    for item in diff["renamed_elements"]:
        sections.append(f'<li class="renamed"><b>RENAMED</b><span>{html.escape(item.get("old_name") or "Unnamed")} → {html.escape(item.get("new_name") or "Unnamed")}</span></li>')
    for heading, items, doc, css in (("ADDED FLOW", diff["added_sequence_flows"], after, "added"),
                                      ("REMOVED FLOW", diff["removed_sequence_flows"], before, "removed")):
        for flow in items:
            source = _label({"id": flow["source_ref"]}, doc); dest = _label({"id": flow["target_ref"]}, doc)
            sections.append(f'<li class="{css}"><b>{heading}</b><span>{html.escape(source)} → {html.escape(dest)}</span></li>')
    summary = "".join(sections) or '<li><span>No semantic changes detected.</span></li>'
    page_title = title or f"{before.path.stem} – Before / After"
    before_marks = {"removed": [x["id"] for x in diff["removed_elements"]], "renamed": [x["id"] for x in diff["renamed_elements"]], "flows": [x["id"] for x in diff["removed_sequence_flows"]]}
    after_marks = {"added": [x["id"] for x in diff["added_elements"]], "renamed": [x["id"] for x in diff["renamed_elements"]], "flows": [x["id"] for x in diff["added_sequence_flows"]]}
    template = _PRESENTATION_TEMPLATE if presentation else _TEMPLATE
    groups = presentation_groups(before, after, diff) if presentation else []
    validation = BasicValidator(after).validate() if presentation else {"error_count": 0}
    rendered = template.format(title=html.escape(page_title), before_name=html.escape(before.path.name), after_name=html.escape(after.path.name),
        added=len(diff["added_elements"]), removed=len(diff["removed_elements"]), renamed=len(diff["renamed_elements"]),
        added_flows=len(diff["added_sequence_flows"]), removed_flows=len(diff["removed_sequence_flows"]), summary=summary,
        group_count=len(groups), presentation_summary=_presentation_summary(groups, before, after),
        validation_errors=validation["error_count"],
        before_suppressed=_json_for_script(_presentation_suppressed_participants(before)),
        after_suppressed=_json_for_script(_presentation_suppressed_participants(after)),
        before_xml=_json_for_script(before_xml), after_xml=_json_for_script(after_xml), before_marks=_json_for_script(before_marks), after_marks=_json_for_script(after_marks))
    target.write_text(rendered, encoding="utf-8")
    if open_browser:
        webbrowser.open(target.as_uri())
    return target, diff


_TEMPLATE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/diagram-js.css"><link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/bpmn-font/css/bpmn.css">
<style>body{{margin:0;font:14px system-ui;color:#17233c;background:#f5f7fa}}header{{padding:22px 28px;background:#fff;border-bottom:3px solid #3267a8}}h1{{margin:0;font-size:22px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px}}.panel,.summary{{background:#fff;border:1px solid #dce2ea;border-radius:6px;overflow:hidden}}h2{{margin:0;padding:12px 16px;font-size:14px;background:#edf2f7}}h2 span{{font-weight:400;color:#536175}}.canvas{{height:55vh;min-height:440px}}.summary{{margin:0 16px 28px;padding-bottom:12px}}.stats{{padding:14px 18px;display:flex;gap:24px;flex-wrap:wrap}}ul{{list-style:none;padding:0 18px;margin:0}}li{{border-left:4px solid #98a2b3;padding:8px 12px;margin:8px 0;display:flex;gap:12px;align-items:baseline}}li b{{font-size:11px;min-width:95px}}li small{{color:#667085}}li.added{{border-color:#159455}}li.removed{{border-color:#d13c3c}}li.renamed{{border-color:#e58a17}}.added .djs-visual>:first-child{{stroke:#159455!important;stroke-width:4px!important}}.removed .djs-visual>:first-child{{stroke:#d13c3c!important;stroke-width:4px!important}}.renamed .djs-visual>:first-child{{stroke:#e58a17!important;stroke-width:4px!important}}.flow-added .djs-visual>path{{stroke:#159455!important;stroke-width:4px!important}}.flow-removed .djs-visual>path{{stroke:#d13c3c!important;stroke-width:4px!important}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}</style></head>
<body><header><h1>BPMN CHANGE PREVIEW</h1><div>{title}</div></header><main class="grid"><section class="panel"><h2>BEFORE · <span>{before_name}</span></h2><div id="before" class="canvas"></div></section><section class="panel"><h2>AFTER · <span>{after_name}</span></h2><div id="after" class="canvas"></div></section></main><section class="summary"><h2>CHANGE SUMMARY</h2><div class="stats"><b>Added: {added}</b><b>Removed: {removed}</b><b>Renamed: {renamed}</b><b>Added flows: {added_flows}</b><b>Removed flows: {removed_flows}</b></div><ul>{summary}</ul></section>
<script src="https://unpkg.com/bpmn-js@17.11.1/dist/bpmn-viewer.development.js"></script><script>const beforeXml={before_xml},afterXml={after_xml};async function show(id,xml,marks){{const viewer=new BpmnJS({{container:'#'+id}});try{{await viewer.importXML(xml);viewer.get('canvas').zoom('fit-viewport');for(const [kind,ids] of Object.entries(marks))for(const eid of ids)try{{viewer.get('canvas').addMarker(eid,kind==='flows'?(id==='before'?'flow-removed':'flow-added'):kind)}}catch(e){{}}}}catch(e){{document.getElementById(id).textContent='Unable to render BPMN: '+e.message}}}}show('before',beforeXml,{before_marks});show('after',afterXml,{after_marks});</script></body></html>'''


_PRESENTATION_TEMPLATE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/diagram-js.css"><link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/bpmn-font/css/bpmn.css">
<style>*{{box-sizing:border-box}}body{{margin:0;background:#eef1f5;color:#17233c;font:15px/1.45 system-ui,sans-serif}}.page{{width:min(1080px,100%);margin:0 auto;background:#fff;min-height:1350px}}header{{padding:25px 34px 18px;border-bottom:3px solid #244f7d;display:flex;justify-content:space-between;align-items:center}}h1{{font-size:23px;margin:0;letter-spacing:.03em}}header p{{margin:3px 0 0;color:#667085}}.toggle button{{border:1px solid #8995a5;background:#fff;padding:8px 12px;color:#24344d;cursor:pointer}}.toggle button.active{{background:#243f63;color:#fff}}.diagrams{{display:grid;grid-template-columns:1fr;gap:10px;padding:14px 22px 8px}}.diagram{{border:1px solid #d8dee8}}.diagram h2{{font-size:17px;margin:0;padding:8px 14px;background:#f3f5f8}}.diagram h2 small{{float:right;font-size:10px;color:#8791a1;font-weight:400}}.canvas{{height:320px}}.bridge{{text-align:center;color:#53657d;font-size:11px;font-weight:700;letter-spacing:.12em;padding:2px}}.metrics{{display:flex;justify-content:center;gap:25px;color:#667085;font-size:12px;padding:8px 15px 15px;border-bottom:1px solid #e3e7ed}}.summary{{padding:18px 34px}}.summary>h2{{font-size:18px;margin:0 0 12px}}article{{display:grid;grid-template-columns:42px 1fr;gap:10px;padding:12px 0;border-top:1px solid #e5e8ed}}.number{{color:#7b8798;font-weight:700}}article h3{{font-size:11px;letter-spacing:.1em;color:#3267a8;margin:0 0 3px}}article strong{{display:block;font-size:15px;margin-bottom:7px}}article small{{display:block;color:#657185;margin-top:5px}}.before-list{{border-left:3px solid #c94d4d;padding-left:10px;margin:6px 0}}.after-list{{border-left:3px solid #198754;padding-left:10px;margin:6px 0}}.status{{display:flex;gap:30px;padding:12px 34px;color:#256a48;border-top:1px solid #e2e7ec}}details{{margin:4px 34px 25px;border:1px solid #dce1e8}}summary{{padding:10px 13px;background:#f4f6f8;cursor:pointer;font-weight:600}}ul{{list-style:none;padding:8px 14px;margin:0}}li{{padding:7px;border-left:3px solid #98a2b3;margin:6px 0;display:flex;gap:10px}}li.added{{border-color:#198754}}li.removed{{border-color:#c94d4d}}li.renamed{{border-color:#dd8b24}}.canvas .djs-element:not(.djs-connection) .djs-visual{{opacity:.73}}.canvas .djs-connection .djs-visual{{opacity:.58}}.canvas .djs-label{{opacity:.98;font-size:13px!important;font-weight:600!important}}.canvas svg text{{font-size:13px!important;font-weight:600!important;fill:#27364d!important}}.added .djs-visual,.removed .djs-visual,.renamed .djs-visual,.flow-added .djs-visual,.flow-removed .djs-visual{{opacity:1!important}}.added .djs-visual>:first-child{{stroke:#198754!important;stroke-width:5px!important}}.removed .djs-visual>:first-child{{stroke:#c94d4d!important;stroke-width:5px!important}}.renamed .djs-visual>:first-child{{stroke:#dd8b24!important;stroke-width:5px!important}}.flow-added .djs-visual>path{{stroke:#198754!important;stroke-width:4px!important}}.flow-removed .djs-visual>path{{stroke:#c94d4d!important;stroke-width:4px!important}}.djs-element.selected .djs-outline{{display:none!important}}@media(max-width:750px){{.page{{min-height:auto}}.canvas{{height:280px}}}}</style></head>
<style>.canvas .djs-label{{font-size:11px!important;font-weight:400!important;opacity:1!important}}.canvas svg text{{font-size:11px!important;font-weight:400!important;fill:#17233c!important}}</style><body><div class="page"><header><div><h1>AI-ASSISTED BPMN TRANSFORMATION</h1><p>Current process → generated process</p></div><div class="toggle"><button id="focused" class="active">Focused changes</button><button id="full">Full process</button></div></header><section class="diagrams"><div class="diagram"><h2>AS-IS <small>{before_name}</small></h2><div id="before" class="canvas"></div></div><div class="diagram"><h2>TO-BE <small>{after_name}</small></h2><div id="after" class="canvas"></div></div></section><div class="bridge">NATURAL-LANGUAGE BPMN TRANSFORMATION</div><div class="metrics"><span>{added} activities added</span><span>{removed} removed</span><span>{added_flows} added flows</span><span>{removed_flows} removed flows</span></div><section class="summary"><h2>OPTIMIZATION SUMMARY · {group_count} STRUCTURAL CHANGES</h2>{presentation_summary}</section><div class="status"><span>✓ BPMN transformation completed</span><span>✓ Structural validation: {validation_errors} errors</span></div><details><summary>Technical BPMN diff ▾</summary><ul>{summary}</ul></details></div>
<script src="https://unpkg.com/bpmn-js@17.11.1/dist/bpmn-viewer.development.js"></script><script>const beforeXml={before_xml},afterXml={after_xml},viewers={{}},marks={{before:{before_marks},after:{after_marks}}},suppressed={{before:{before_suppressed},after:{after_suppressed}}};function suppressPresentationChrome(id,viewer){{const registry=viewer.get('elementRegistry');for(const elementId of suppressed[id]){{const element=registry.get(elementId),gfx=element&&registry.getGraphics(element);if(gfx)gfx.style.display='none'}}}}async function show(id,xml){{const viewer=new BpmnJS({{container:'#'+id}});viewers[id]=viewer;await viewer.importXML(xml);suppressPresentationChrome(id,viewer);const canvas=viewer.get('canvas');canvas.zoom('fit-viewport');for(const [kind,ids] of Object.entries(marks[id]))for(const eid of ids)try{{canvas.addMarker(eid,kind==='flows'?(id==='before'?'flow-removed':'flow-added'):kind)}}catch(e){{}}requestAnimationFrame(()=>focus(id))}}function focus(id){{const viewer=viewers[id],registry=viewer.get('elementRegistry'),ids=Object.values(marks[id]).flat(),changed=ids.map(x=>registry.get(x)).filter(e=>e&&Number.isFinite(e.x)&&Number.isFinite(e.width));if(!changed.length)return viewer.get('canvas').zoom('fit-viewport');const all=registry.getAll().filter(e=>e&&Number.isFinite(e.x)&&Number.isFinite(e.width)&&!e.labelTarget&&!suppressed[id].includes(e.id));let x=Math.min(...changed.map(e=>e.x)),y=Math.min(...changed.map(e=>e.y)),r=Math.max(...changed.map(e=>e.x+e.width)),b=Math.max(...changed.map(e=>e.y+e.height));const near=all.filter(e=>e.x<r+180&&e.x+e.width>x-180&&e.y<b+100&&e.y+e.height>y-100);if(near.length){{x=Math.min(...near.map(e=>e.x));y=Math.min(...near.map(e=>e.y));r=Math.max(...near.map(e=>e.x+e.width));b=Math.max(...near.map(e=>e.y+e.height))}}viewer.get('canvas').viewbox({{x:x-70,y:y-55,width:r-x+140,height:b-y+110}})}}document.getElementById('focused').onclick=()=>{{for(const id of ['before','after'])focus(id);focused.classList.add('active');full.classList.remove('active')}};document.getElementById('full').onclick=()=>{{for(const id of ['before','after'])viewers[id].get('canvas').zoom('fit-viewport');full.classList.add('active');focused.classList.remove('active')}};show('before',beforeXml);show('after',afterXml);</script></body></html>'''
