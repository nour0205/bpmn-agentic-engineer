from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict, deque
from pathlib import Path

from bpmn_agentic_engineer.analysis.models import AnalysisFinding, BpmnAnalysisResult
from bpmn_agentic_engineer.bpmn import BpmnDocument
from bpmn_agentic_engineer.validation import BasicValidator

TASK_TYPES = {"task", "userTask", "manualTask", "serviceTask", "sendTask", "receiveTask", "scriptTask", "businessRuleTask"}
GATEWAY_TYPES = {"exclusiveGateway", "inclusiveGateway", "parallelGateway", "complexGateway", "eventBasedGateway"}
EVENT_TYPES = {"startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}
HUMAN_TYPES = {"userTask", "manualTask"}
DATA_SIGNALS = ("saisir", "saisie", "renseigner", "remplir", "enregistrer", "copier", "exporter vers excel", "export to excel", "enter", "input", "fill", "manually update", "mettre a jour manuellement")
CONTROL_SIGNALS = ("valider", "validation", "approuver", "verifier", "controler", "controle", "revue", "review", "approve", "validate", "verification")
COMMUNICATION_SIGNALS = ("e-mail", "email", " mail", "telephone", "phone", "transmission manuelle")


def _norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", (value or "").casefold())
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


class BpmnAnalyzer:
    """Deterministic, read-only structural analysis over the trusted BPMN model."""

    def analyze(self, path: str | Path) -> BpmnAnalysisResult:
        document = BpmnDocument(path)
        nodes = document.elements
        successors = {identifier: tuple(sorted(document.outgoing[identifier])) for identifier in nodes}
        predecessors = {identifier: tuple(sorted(document.incoming[identifier])) for identifier in nodes}
        starts = sorted(i for i in nodes if not predecessors[i] and nodes[i].type != "boundaryEvent")
        ends = sorted(i for i in nodes if not successors[i] and nodes[i].type != "boundaryEvent")
        reachable = self._reachable(starts, successors)
        unreachable = sorted(set(nodes) - reachable)
        components = self._strong_components(successors)
        cycles = [component for component in components if len(component) > 1 or (len(component) == 1 and component[0] in successors[component[0]])]
        handoffs = self._handoffs(document)
        findings: list[AnalysisFinding] = []
        findings.extend(self._duplicates(document))
        findings.extend(self._human_chains(document, successors, predecessors))
        findings.extend(self._lexical(document))
        findings.extend(self._handoff_findings(document, handoffs))
        findings.extend(self._gateway_findings(document, successors, predecessors))
        findings.extend(self._cycle_findings(document, cycles))
        for identifier in unreachable:
            findings.append(self._finding("UNREACHABLE_NODE", "connectivity", "Unreachable flow node", (identifier,), document,
                                          "Not reachable from any explicit or implicit process entry.", severity="medium"))
        for identifier in ends:
            if nodes[identifier].type != "endEvent":
                findings.append(self._finding("DEAD_END", "connectivity", "Non-end node without successor", (identifier,), document,
                                              "The node has no outgoing sequence flow."))
        findings.sort(key=lambda f: (f.code, f.element_ids, f.evidence))
        types = Counter(element.type for element in nodes.values())
        metrics = {
            "total_flow_nodes": len(nodes), "sequence_flows": len(document.sequence_flows),
            "tasks": sum(types[t] for t in TASK_TYPES), "user_tasks": types["userTask"],
            "service_tasks": types["serviceTask"], "manual_tasks": types["manualTask"],
            "call_activities": types["callActivity"], "gateways": sum(types[t] for t in GATEWAY_TYPES),
            "exclusive_gateways": types["exclusiveGateway"], "parallel_gateways": types["parallelGateway"],
            "events": sum(types[t] for t in EVENT_TYPES), "lanes": len(document.lanes),
            "named_elements": sum(bool(e.name) for e in nodes.values()), "unnamed_elements": sum(not e.name for e in nodes.values()),
            "start_like_nodes": len(starts), "end_like_nodes": len(ends), "unreachable_nodes": len(unreachable),
            "dead_end_non_end_nodes": sum(nodes[i].type != "endEvent" for i in ends),
            "nodes_without_predecessor": len(starts), "nodes_without_successor": len(ends),
            "lane_handoffs": len(handoffs), "cycles": len(cycles),
            "gateway_splits": sum(len(successors[i]) > 1 for i, e in nodes.items() if e.type in GATEWAY_TYPES),
            "gateway_merges": sum(len(predecessors[i]) > 1 for i, e in nodes.items() if e.type in GATEWAY_TYPES),
            "longest_structural_path": self._condensed_longest_path(components, successors),
            "longest_linear_task_chain": self._longest_linear_task_chain(document, successors, predecessors),
        }
        process = next((p for p in document.processes.values() if p.get("name")), None)
        validation = BasicValidator(document).validate()
        return BpmnAnalysisResult(str(document.path), process.get("name") if process else None, metrics,
            tuple(document.lanes[k] for k in sorted(document.lanes)),
            {"nodes": len(nodes), "edges": len(document.sequence_flows), "connected_components": self._weak_components(successors),
             "start_node_ids": starts, "end_node_ids": ends, "cycle_count": len(cycles),
             "longest_path_method": "weighted longest path over the strongly-connected-component condensation DAG"},
            tuple(findings), {k: validation[k] for k in ("valid_for_agentic_editing", "error_count", "warning_count", "info_count", "issues")})

    @staticmethod
    def _reachable(starts, successors):
        seen, queue = set(starts), deque(starts)
        while queue:
            for item in successors[queue.popleft()]:
                if item not in seen: seen.add(item); queue.append(item)
        return seen

    @staticmethod
    def _strong_components(successors):
        index = 0; stack = []; on_stack = set(); indices = {}; low = {}; result = []
        def visit(node):
            nonlocal index
            indices[node] = low[node] = index; index += 1; stack.append(node); on_stack.add(node)
            for nxt in successors[node]:
                if nxt not in successors: continue
                if nxt not in indices: visit(nxt); low[node] = min(low[node], low[nxt])
                elif nxt in on_stack: low[node] = min(low[node], indices[nxt])
            if low[node] == indices[node]:
                component = []
                while True:
                    item = stack.pop(); on_stack.remove(item); component.append(item)
                    if item == node: break
                result.append(tuple(sorted(component)))
        for node in sorted(successors):
            if node not in indices: visit(node)
        return result

    @staticmethod
    def _weak_components(successors):
        undirected = defaultdict(set)
        for source, targets in successors.items():
            for target in targets: undirected[source].add(target); undirected[target].add(source)
        unseen = set(successors); count = 0
        while unseen:
            count += 1; queue = [min(unseen)]; unseen.remove(queue[0])
            while queue:
                for nxt in undirected[queue.pop()]:
                    if nxt in unseen: unseen.remove(nxt); queue.append(nxt)
        return count

    @staticmethod
    def _condensed_longest_path(components, successors):
        owner = {node: i for i, comp in enumerate(components) for node in comp}; edges = defaultdict(set); indegree = Counter()
        for node, targets in successors.items():
            for target in targets:
                if target in owner and owner[node] != owner[target] and owner[target] not in edges[owner[node]]:
                    edges[owner[node]].add(owner[target]); indegree[owner[target]] += 1
        queue = deque(sorted(i for i in range(len(components)) if not indegree[i])); depth = {i: len(components[i]) for i in queue}
        while queue:
            current = queue.popleft()
            for nxt in sorted(edges[current]):
                depth[nxt] = max(depth.get(nxt, 0), depth[current] + len(components[nxt])); indegree[nxt] -= 1
                if indegree[nxt] == 0: queue.append(nxt)
        return max(depth.values(), default=0)

    def _finding(self, code, category, title, ids, document, evidence, severity="info", metrics=None, lanes=None):
        elements = [document.elements[i] for i in ids if i in document.elements]
        return AnalysisFinding(code, category, title, "Deterministic structural pattern detected.", severity, 1.0, tuple(ids),
            tuple(e.name or "Unnamed element" for e in elements), tuple(lanes or dict.fromkeys(e.lane_name for e in elements if e.lane_name)), evidence, metrics or {})

    def _duplicates(self, document):
        groups = defaultdict(list)
        for e in document.elements.values():
            if e.name: groups[_norm(e.name)].append(e.id)
        return [self._finding("DUPLICATE_LABEL", "labels", "Duplicate visible label", tuple(sorted(ids)), document,
                f"Exact normalized label occurs {len(ids)} times.", metrics={"occurrences": len(ids)})
                for _, ids in sorted(groups.items()) if len(ids) > 1]

    def _human_chains(self, document, successors, predecessors):
        findings = []; visited = set()
        for start in sorted(document.elements):
            if document.elements[start].type not in HUMAN_TYPES or start in visited: continue
            human_preds = [p for p in predecessors[start] if p in document.elements and document.elements[p].type in HUMAN_TYPES]
            if len(human_preds) == 1 and len(successors[human_preds[0]]) == 1: continue
            chain = [start]
            while len(successors[chain[-1]]) == 1:
                nxt = successors[chain[-1]][0]
                if nxt not in document.elements or document.elements[nxt].type not in HUMAN_TYPES or len(predecessors[nxt]) != 1: break
                chain.append(nxt)
            visited.update(chain)
            if len(chain) >= 2:
                findings.append(self._finding("SEQUENTIAL_HUMAN_TASK_CHAIN", "sequence", "Sequential human-oriented task chain",
                    tuple(chain), document, f"{len(chain)} consecutive userTask/manualTask nodes without branching.",
                    severity="medium" if len(chain) >= 3 else "info", metrics={"length": len(chain)}))
        return findings

    @staticmethod
    def _longest_linear_task_chain(document, successors, predecessors):
        longest = 0
        for start, element in sorted(document.elements.items()):
            if element.type not in TASK_TYPES:
                continue
            prior = [p for p in predecessors[start] if p in document.elements and document.elements[p].type in TASK_TYPES]
            if len(prior) == 1 and len(successors[prior[0]]) == 1:
                continue
            length, current, seen = 1, start, {start}
            while len(successors[current]) == 1:
                nxt = successors[current][0]
                if nxt in seen or nxt not in document.elements or document.elements[nxt].type not in TASK_TYPES or len(predecessors[nxt]) != 1:
                    break
                seen.add(nxt); current = nxt; length += 1
            longest = max(longest, length)
        return longest

    def _lexical(self, document):
        result = []
        for e in sorted(document.elements.values(), key=lambda x: x.id):
            if e.type not in TASK_TYPES or not e.name: continue
            normalized = _norm(e.name)
            for code, category, title, signals in (("DATA_ENTRY_SIGNAL", "lexical", "Data-entry lexical signal", DATA_SIGNALS),
                    ("CONTROL_ACTIVITY_SIGNAL", "control", "Control activity lexical signal", CONTROL_SIGNALS),
                    ("MANUAL_COMMUNICATION_SIGNAL", "communication", "Manual communication lexical signal", COMMUNICATION_SIGNALS)):
                matched = next((signal for signal in signals if signal.strip() in normalized), None)
                if matched:
                    result.append(self._finding(code, category, title, (e.id,), document, f'Task label contains the lexical signal "{matched.strip()}".', metrics={"matched_signal": matched.strip()}))
            if "export" in normalized and "excel" in normalized and not any(f.code == "DATA_ENTRY_SIGNAL" and e.id in f.element_ids for f in result):
                result.append(self._finding("DATA_ENTRY_SIGNAL", "lexical", "Data-entry lexical signal", (e.id,), document,
                    'Task label contains both "export" and "Excel".', metrics={"matched_signal": "export … Excel"}))
        return result

    @staticmethod
    def _handoffs(document):
        result = []
        for flow in sorted(document.sequence_flows.values(), key=lambda f: f.id):
            source, target = document.elements.get(flow.source_ref), document.elements.get(flow.target_ref)
            if source and target and source.lane_name and target.lane_name and source.lane_name != target.lane_name:
                result.append((flow, source, target))
        return result

    def _handoff_findings(self, document, handoffs):
        result = []
        for flow, source, target in handoffs:
            result.append(self._finding("LANE_HANDOFF", "lanes", "Cross-lane handoff", (source.id, target.id), document,
                f'Sequence flow crosses from "{source.lane_name}" to "{target.lane_name}".', lanes=(source.lane_name, target.lane_name)))
        for first in handoffs:
            _, a, b = first
            for second in handoffs:
                _, b2, c = second
                if b.id == b2.id and a.lane_name == c.lane_name and a.lane_name != b.lane_name:
                    result.append(self._finding("LANE_BACK_AND_FORTH", "lanes", "Lane back-and-forth", (a.id, b.id, c.id), document,
                        f'Consecutive flows follow {a.lane_name} → {b.lane_name} → {c.lane_name}.', lanes=(a.lane_name, b.lane_name, c.lane_name)))
        return result

    def _gateway_findings(self, document, successors, predecessors):
        result = []
        for e in sorted(document.elements.values(), key=lambda x: x.id):
            if e.type not in GATEWAY_TYPES: continue
            metrics = {"bpmn_type": e.type, "incoming": len(predecessors[e.id]), "outgoing": len(successors[e.id]),
                       "predecessor_names": [document.elements[i].name for i in predecessors[e.id] if i in document.elements],
                       "successor_names": [document.elements[i].name for i in successors[e.id] if i in document.elements]}
            if len(successors[e.id]) > 1: result.append(self._finding("GATEWAY_SPLIT", "gateway", "Gateway split", (e.id,), document, f"Gateway has {len(successors[e.id])} outgoing flows.", metrics=metrics))
            if len(predecessors[e.id]) > 1: result.append(self._finding("GATEWAY_MERGE", "gateway", "Gateway merge", (e.id,), document, f"Gateway has {len(predecessors[e.id])} incoming flows.", metrics=metrics))
        return result

    def _cycle_findings(self, document, cycles):
        return [self._finding("CYCLE", "graph", "Directed cycle", tuple(component), document,
                f"Strongly connected component contains {len(component)} flow node(s).", metrics={"node_count": len(component)}) for component in cycles]
