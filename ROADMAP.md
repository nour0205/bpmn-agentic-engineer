# Roadmap

## Milestone 1 — Read-only BPMN intelligence

- [x] BPMN XML loader
- [x] element and lane extraction
- [x] sequence-flow graph
- [x] element search
- [x] predecessor/successor context
- [x] path lookup
- [x] deterministic basic validation
- [x] CLI
- [x] read-only MCP tools
- [ ] run against all existing BPMN examples
- [ ] connect the existing semantic parser through an adapter
- [ ] add complex BPMN regression fixtures

## Milestone 2 — Change interpretation

Input:

```text
"Add a correction task after financial rejection and return it for resubmission."
```

Output:

```json
{
  "intent": "add_rejection_and_resubmission_path",
  "affected_elements": [],
  "operations": [],
  "constraints": [],
  "acceptance_criteria": [],
  "uncertainties": []
}
```

Deliverables:

- `ChangeRequest`
- `ResolvedChangeRequest`
- `ModificationPlan`
- element-grounding step
- plan review checkpoint

## Milestone 3 — Atomic BPMN editing tools

Initial supported transformations:

- rename a task;
- insert a task between two nodes;
- change a task lane;
- add a rejection branch;
- parallelize two independent tasks.

Every operation must:

- create a new version;
- preserve the original;
- produce a semantic diff;
- return affected IDs;
- be reversible.

## Milestone 4 — Verification and repair

- XML and reference validation
- reachability
- gateway consistency
- loop checks
- affected-path regression tests
- critic/verifier agent
- bounded repair loop

## Milestone 5 — Human-in-the-loop LangGraph workflow

```text
interpret -> inspect -> plan -> approve plan -> apply
          -> validate -> repair? -> compare -> approve result
```

Add persistence, checkpoints, rollback and traces.
