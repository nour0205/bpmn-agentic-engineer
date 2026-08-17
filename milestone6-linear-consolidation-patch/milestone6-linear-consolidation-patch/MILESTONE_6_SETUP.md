# Milestone 6 — Safe linear task consolidation

This patch adds one controlled operation:

```text
replace_linear_task_sequence
```

It replaces two or more consecutive, unbranched tasks with one task while preserving the original predecessor and successor.

## Files to copy

Copy the patch `src/bpmn_agentic_engineer/...` files over the matching files in the repository. Do not copy the `src` directory itself inside the package.

PowerShell from the repository root:

```powershell
Copy-Item -Recurse -Force `
  ".\milestone6-linear-consolidation-patch\src\bpmn_agentic_engineer\*" `
  ".\src\bpmn_agentic_engineer\"

Copy-Item -Recurse -Force `
  ".\milestone6-linear-consolidation-patch\tests\*" `
  ".\tests\"
```

## Verify

```powershell
uv run python -m py_compile `
  ".\src\bpmn_agentic_engineer\models.py" `
  ".\src\bpmn_agentic_engineer\planning\planner.py" `
  ".\src\bpmn_agentic_engineer\execution\executor.py" `
  ".\src\bpmn_agentic_engineer\llm\schema.py" `
  ".\src\bpmn_agentic_engineer\llm\interpreter.py" `
  ".\src\bpmn_agentic_engineer\llm\prompts.py" `
  ".\src\bpmn_agentic_engineer\agent\nodes.py" `
  ".\src\bpmn_agentic_engineer\agent\service.py" `
  ".\src\bpmn_agentic_engineer\agent\state.py" `
  ".\src\bpmn_agentic_engineer\cli.py"

uv run pytest
```

## Deterministic local test

```powershell
uv run bpmn-agent plan `
  ".\evaluation\scenario_001\input\as_is.bpmn" `
  "Fusionne les activités manuelles en une seule tâche automatisée." `
  --operation "replace_linear_task_sequence" `
  --source-query "Exporter les résultats des simulations vers un fichier Excel" `
  --source-query "Calculer manuellement la couverture de stock" `
  --source-query "Consolider les résultats de couverture de stock" `
  --new-name "Génération automatique de la couverture de stock relatif à chaque simulation (Autonomie)" `
  --new-bpmn-type "serviceTask" `
  --lane-name "Direction d'Approvisionnement" `
  --save-plan ".\evaluation\scenario_001\results\step_01_plan.json"
```

Review the exact plan, then execute it:

```powershell
uv run bpmn-agent execute `
  ".\evaluation\scenario_001\results\step_01_plan.json" `
  ".\evaluation\scenario_001\generated\step_01_merged.bpmn" `
  --approved
```

## Qwen test

The remote model now returns `source_queries` and `new_bpmn_type`. Start the normal Kaggle workflow with the human prompt:

```powershell
uv run bpmn-agent agent-start `
  ".\evaluation\scenario_001\input\as_is.bpmn" `
  "Fusionne les activités « Exporter les résultats des simulations vers un fichier Excel », « Calculer manuellement la couverture de stock » et « Consolider les résultats de couverture de stock » en une seule tâche de service « Génération automatique de la couverture de stock relatif à chaque simulation (Autonomie) », dans le couloir Direction d'Approvisionnement." `
  --interpretation-mode qwen3-kaggle `
  --kaggle-kernel-ref "nourkouider05/bpmn-qwen3-interpreter" `
  --output-path ".\evaluation\scenario_001\generated\step_01_merged_qwen.bpmn"
```

After Kaggle is complete, resume with the real run ID and `--fetch-llm`, inspect the checksummed plan, then approve it.
