# Milestone 4 — Durable Agent Orchestration

This patch adds a LangGraph workflow around the existing deterministic BPMN tools.
The graph interprets state and coordinates tools, but it never writes XML directly.
Only `BpmnPlanExecutor` performs approved edits on a new file.

## Files added or replaced

```text
pyproject.toml
src/bpmn_agentic_engineer/cli.py
src/bpmn_agentic_engineer/mcp_server/server.py
src/bpmn_agentic_engineer/agent/
  __init__.py
  state.py
  nodes.py
  routing.py
  graph.py
  service.py
tests/test_agent_workflow.py
```

The existing parser, planner, validator and executor are not replaced.

## Install

From the project root:

```powershell
Expand-Archive `
  ".\milestone4-agent-orchestration-patch.zip" `
  -DestinationPath ".\_milestone4" `
  -Force

Copy-Item `
  ".\_milestone4\milestone4-agent-orchestration-patch\src\*" `
  ".\src" `
  -Recurse `
  -Force

Copy-Item `
  ".\_milestone4\milestone4-agent-orchestration-patch\tests\*" `
  ".\tests" `
  -Recurse `
  -Force

Copy-Item `
  ".\_milestone4\milestone4-agent-orchestration-patch\pyproject.toml" `
  ".\pyproject.toml" `
  -Force
```

Install all extras and run the suite:

```powershell
uv sync --extra all
uv run pytest
```

## Workflow

```text
received
→ inspecting
→ needs_clarification (optional interrupt)
→ waiting_for_approval (mandatory interrupt)
→ executing
→ validating
→ completed
```

A failed post-execution validation enters `repairing`, then stops safely because
Milestone 4 deliberately contains no automatic repair policy yet.

## Start a run

PowerShell-safe explicit hints:

```powershell
uv run bpmn-agent agent-start `
  "data\bpmn\Approvisionnement par Appel d'offres.bpmn" `
  "Ajouter une tâche après une activité" `
  --target-query "Créer un dossier d'appel d'offres et renseigner son numéro" `
  --new-name "Valider le dossier d'appel d'offres" `
  --process-id "Id_54e28588-82ab-4392-a9be-a85620d80a90" `
  --output-path ".\output\bpmn\Approvisionnement par Appel d'offres_AGENT.bpmn"
```

Expected status:

```json
{
  "status": "waiting_for_approval",
  "run_id": "run_...",
  "approval_required": true,
  "plan_checksum": "..."
}
```

Keep the returned `run_id`.

## Approve and resume

```powershell
uv run bpmn-agent agent-resume "run_..." --approved
```

The same persisted plan is executed. It is not regenerated after approval.
Expected final status:

```json
{
  "status": "completed",
  "execution_result": {
    "status": "execution_succeeded"
  }
}
```

Reject instead:

```powershell
uv run bpmn-agent agent-resume "run_..." --rejected
```

## Clarification loop

Start without a process ID when two variants contain the same activity. The run
will pause with `needs_clarification`. Resume it with the chosen process:

```powershell
uv run bpmn-agent agent-resume "run_..." `
  --process-id "Id_54e28588-82ab-4392-a9be-a85620d80a90"
```

It will recompute the baseline and plan, then pause at approval.

## Read persisted status

```powershell
uv run bpmn-agent agent-status "run_..."
```

Checkpoints are stored by default in:

```text
.bpmn_agent/checkpoints.sqlite
```

Do not delete or move that database while runs are waiting for clarification or
approval. Stable graph node names are also required for old runs to resume.

## MCP Inspector

Restart the server:

```powershell
uv run mcp dev src/bpmn_agentic_engineer/mcp_server/server.py
```

New tools:

```text
run_bpmn_agent
resume_bpmn_agent
get_bpmn_agent_run
```

For approval through MCP, call `resume_bpmn_agent` with the exact `run_id`,
`approved=true`, and an `output_path` if one was not supplied at start.

## Scope

This milestone is deterministic orchestration only. No LLM provider is required.
The later LLM milestone will be limited to language interpretation and tool
coordination; checksummed planning, approval, execution and validation remain
deterministic.
