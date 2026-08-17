# Milestone 2 — Textual BPMN Change Planning

This patch adds a read-only planning layer. It does not modify BPMN XML.

## Files

Copy the `src` and `tests` directories from this patch into the project root and allow replacement of existing files.

New package:

- `src/bpmn_agentic_engineer/planning/grounding.py`
- `src/bpmn_agentic_engineer/planning/planner.py`
- `src/bpmn_agentic_engineer/planning/__init__.py`

Updated files:

- `src/bpmn_agentic_engineer/models.py`
- `src/bpmn_agentic_engineer/bpmn/inspector.py`
- `src/bpmn_agentic_engineer/mcp_server/server.py`
- `src/bpmn_agentic_engineer/cli.py`

## Verify

```powershell
uv run pytest
```

Expected result:

```text
10 passed
```

## CLI test

```powershell
uv run bpmn-agent plan `
  "data\bpmn\Approvisionnement par Appel d'offres.bpmn" `
  'Ajouter une tâche "Valider le dossier d’appel d’offres" après "Créer un dossier d’appel d’offres et renseigner son numéro"'
```

Because that activity exists in more than one process variant, the expected status is:

```json
"status": "requires_clarification"
```

Resolve it with the desired process ID:

```powershell
uv run bpmn-agent plan `
  "data\bpmn\Approvisionnement par Appel d'offres.bpmn" `
  'Ajouter une tâche "Valider le dossier d’appel d’offres" après "Créer un dossier d’appel d’offres et renseigner son numéro"' `
  --process-id "Id_54e28588-82ab-4392-a9be-a85620d80a90"
```

Expected status:

```json
"status": "ready_for_approval"
```

The plan should contain four atomic operations:

1. add the new task;
2. remove the original sequence flow;
3. connect the target to the new task;
4. reconnect the new task to the original successor.

## MCP Inspector

Restart the MCP development server:

```powershell
uv run mcp dev src/bpmn_agentic_engineer/mcp_server/server.py
```

Open **Tools** and refresh the list. A sixth tool should appear:

```text
plan_bpmn_change
```

Use the same BPMN path and request. The tool is read-only and never changes the source file.
