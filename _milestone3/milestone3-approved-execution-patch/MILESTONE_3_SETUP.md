# Milestone 3 — Approved BPMN Plan Execution

This patch adds controlled execution of a checksummed modification plan on a **new BPMN file**. The source file is never overwritten.

## Files added

- `src/bpmn_agentic_engineer/integrity.py`
- `src/bpmn_agentic_engineer/execution/__init__.py`
- `src/bpmn_agentic_engineer/execution/executor.py`
- `tests/test_execution.py`
- `tests/fixtures/execution_process.bpmn`

## Files replaced

- `src/bpmn_agentic_engineer/planning/planner.py`
- `src/bpmn_agentic_engineer/cli.py`
- `src/bpmn_agentic_engineer/mcp_server/server.py`

The corrected `document.py`, validator, models, grounding module and inspector remain unchanged.

## Install

From the project root:

```powershell
Expand-Archive `
  ".\milestone3-approved-execution-patch.zip" `
  -DestinationPath ".\_milestone3" `
  -Force

Copy-Item `
  ".\_milestone3\milestone3-approved-execution-patch\src\*" `
  ".\src" `
  -Recurse `
  -Force

Copy-Item `
  ".\_milestone3\milestone3-approved-execution-patch\tests\*" `
  ".\tests" `
  -Recurse `
  -Force
```

## Test

```powershell
uv run pytest
```

The patch itself was tested with the starter repository and produced `14 passed`.

## Generate and save an approvable plan

```powershell
uv run bpmn-agent plan `
  "data\bpmn\Approvisionnement par Appel d'offres.bpmn" `
  "Ajouter une tâche après une activité" `
  --target-query "Créer un dossier d'appel d'offres et renseigner son numéro" `
  --new-name "Valider le dossier d'appel d'offres" `
  --process-id "Id_54e28588-82ab-4392-a9be-a85620d80a90" `
  --save-plan ".\output\plans\appel-offres-add-validation.json"
```

Review the saved JSON. It must contain:

- `"status": "ready_for_approval"`
- `"requires_approval": true`
- `"source_sha256": "..."`
- `"plan_checksum": "..."`

## Execute the exact approved plan

```powershell
uv run bpmn-agent execute `
  ".\output\plans\appel-offres-add-validation.json" `
  ".\output\bpmn\Approvisionnement par Appel d'offres_MODIFIED.bpmn" `
  --approved
```

The executor:

- verifies explicit approval;
- verifies the plan checksum;
- verifies that the source file has not changed since planning;
- refuses to overwrite the source or an existing output file;
- applies atomic BPMN XML changes;
- updates BPMN DI shapes and edges;
- validates the temporary result;
- commits the output only when validation succeeds;
- returns a before/after structural diff.

## Verify

```powershell
uv run bpmn-agent validate `
  ".\output\bpmn\Approvisionnement par Appel d'offres_MODIFIED.bpmn"

uv run bpmn-agent find `
  ".\output\bpmn\Approvisionnement par Appel d'offres_MODIFIED.bpmn" `
  "Valider le dossier d'appel d'offres"
```

Open the generated file in Bizagi and confirm that the new task is visible in the `SPCM` lane between the selected activity and its former successor.

## MCP Inspector

Restart the server:

```powershell
uv run mcp dev src/bpmn_agentic_engineer/mcp_server/server.py
```

The server now exposes:

- `plan_bpmn_change`
- `execute_bpmn_plan`

For execution, pass the exact plan object returned by `plan_bpmn_change`, choose a new output path and set `approved` to `true`.
