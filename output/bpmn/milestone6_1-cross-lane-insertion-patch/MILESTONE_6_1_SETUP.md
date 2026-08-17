# Milestone 6.1 — Cross-lane task insertion

This patch fixes insertion semantics when the new task belongs to a different lane from the existing anchor task.

## What changes

- For `insert_task_before` and `insert_task_after`, `lane_name` now identifies the destination lane of the new task.
- The anchor task is grounded independently of that destination lane.
- Insertions honor `new_bpmn_type` (`userTask`, `serviceTask`, etc.).
- Qwen is explicitly told that the anchor and destination lane may differ.

## Copy into the project

From the project root:

```powershell
$patchRoot = ".\milestone6_1-cross-lane-insertion-patch"

Copy-Item -Recurse -Force `
  "$patchRoot\src\bpmn_agentic_engineer\*" `
  ".\src\bpmn_agentic_engineer\"

Copy-Item -Recurse -Force `
  "$patchRoot\tests\*" `
  ".\tests\"

uv run pytest
```

## Step 2 deterministic plan

```powershell
uv run bpmn-agent plan `
  ".\evaluation\scenario_001\generated\step_01_merged.bpmn" `
  "Ajoute l'activité « Effectuer une analyse financiére des simulations » avant « Choisir la simulation (solution) optimale », dans le couloir Direction Financiére." `
  --operation "insert_task_before" `
  --target-query "Choisir la simulation (solution) optimale" `
  --new-name "Effectuer une analyse financiére des simulations" `
  --new-bpmn-type "userTask" `
  --lane-name "Direction Financiére" `
  --save-plan ".\evaluation\scenario_001\results\step_02_plan.json"
```

Review the plan, then execute:

```powershell
uv run bpmn-agent execute `
  ".\evaluation\scenario_001\results\step_02_plan.json" `
  ".\evaluation\scenario_001\generated\step_02_financial_analysis.bpmn" `
  --approved
```
