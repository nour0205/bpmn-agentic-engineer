# BPMN Agentic Engineer

Foundation for a **natural-language BPMN engineering agent**.

The first milestone is deliberately read-only:

1. load BPMN 2.0 XML;
2. inspect processes, tasks, events, gateways, lanes and sequence flows;
3. locate elements mentioned in a user request;
4. retrieve local graph context and paths;
5. run deterministic structural validation;
6. expose those capabilities as MCP tools.

No LLM is allowed to modify BPMN XML in this milestone.

## Architecture

```text
BPMN file
   |
   v
BpmnDocument
   |
   +--> ProcessInspector
   |      +--> summary
   |      +--> element search
   |      +--> predecessor/successor context
   |      +--> path lookup
   |
   +--> BasicValidator
   |      +--> duplicate IDs
   |      +--> dangling sequence flows
   |      +--> start/end checks
   |      +--> reachability checks
   |
   +--> Read-only MCP server
```

## Setup with `uv`

```bash
cd bpmn-agentic-engineer-starter
uv venv
uv sync --extra all
```

Or with `pip`:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -e ".[all]"
```

## Run the CLI

Inspect a BPMN:

```bash
bpmn-agent inspect tests/fixtures/simple_process.bpmn
```

Find an element:

```bash
bpmn-agent find tests/fixtures/simple_process.bpmn "financial validation"
```

Inspect an element's local context:

```bash
bpmn-agent context tests/fixtures/simple_process.bpmn Task_Finance
```

Find a path:

```bash
bpmn-agent path tests/fixtures/simple_process.bpmn StartEvent_1 EndEvent_1
```

Validate:

```bash
bpmn-agent validate tests/fixtures/simple_process.bpmn
```

All commands return JSON so they can later be consumed by an agent.

## Run the read-only MCP server

Install the MCP extra, then run:

```bash
uv run mcp dev src/bpmn_agentic_engineer/mcp_server/server.py
```

The initial MCP tools are:

- `inspect_bpmn`
- `find_bpmn_elements`
- `get_bpmn_element_context`
- `find_bpmn_path`
- `validate_bpmn`

They are explicitly marked as read-only.

## Run tests

```bash
pytest
```

A standard-library fallback also works:

```bash
python -m unittest discover -s tests
```

## Immediate next tasks

1. Test the inspector on the six existing BPMN files.
2. Compare its results with the semantic JSON from the procedure-generator project.
3. Add fixtures for gateways, loops, subprocesses and lanes.
4. Define the structured `ChangeRequest` and `ModificationPlan` schemas.
5. Only then add write-capable atomic BPMN tools.
