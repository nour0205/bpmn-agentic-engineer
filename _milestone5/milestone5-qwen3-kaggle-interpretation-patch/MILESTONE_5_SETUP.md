# Milestone 5 — Qwen3-8B interpretation through Kaggle CLI

This patch adds an LLM-assisted interpretation stage without giving the model permission to edit BPMN XML.

The complete flow is:

```text
natural-language request
→ compact ID-free BPMN catalogue
→ Qwen3-8B on Kaggle GPU
→ strict JSON validation locally
→ process-alias mapping locally
→ deterministic grounding and planning
→ clarification when ambiguous
→ human approval
→ safe execution on a copy
```

## 1. Install the patch

From the project root in PowerShell:

```powershell
Expand-Archive `
  ".\milestone5-qwen3-kaggle-interpretation-patch.zip" `
  -DestinationPath ".\_milestone5" `
  -Force
```

```powershell
Copy-Item `
  ".\_milestone5\milestone5-qwen3-kaggle-interpretation-patch\src\*" `
  ".\src" `
  -Recurse `
  -Force
```

```powershell
Copy-Item `
  ".\_milestone5\milestone5-qwen3-kaggle-interpretation-patch\tests\*" `
  ".\tests" `
  -Recurse `
  -Force
```

```powershell
Copy-Item `
  ".\_milestone5\milestone5-qwen3-kaggle-interpretation-patch\pyproject.toml" `
  ".\pyproject.toml" `
  -Force
```

Install dependencies:

```powershell
uv sync --extra all
```

Run the complete local test suite:

```powershell
uv run pytest
```

Expected result for the supplied project state:

```text
21 passed, 1 skipped
```

The skipped test is the existing optional LangGraph test when its runtime dependency is unavailable in the test environment.

## 2. Authenticate Kaggle CLI

Check that the CLI is installed inside the project environment:

```powershell
uv run kaggle --version
```

Authenticate when needed:

```powershell
uv run kaggle auth login
```

A token already configured through `KAGGLE_API_TOKEN`, `~/.kaggle/access_token`, or the legacy `kaggle.json` also works.

## 3. Start an LLM-assisted run

Replace `<your-kaggle-username>` with the username that owns the Kaggle kernel.

```powershell
uv run bpmn-agent agent-start `
  "data\bpmn\Approvisionnement par Appel d'offres.bpmn" `
  "Ajoute une validation du dossier par le SPCM avant la rédaction du cahier des charges" `
  --interpretation-mode qwen3-kaggle `
  --kaggle-kernel-ref "<your-kaggle-username>/bpmn-qwen3-interpreter" `
  --output-path ".\output\bpmn\Approvisionnement par Appel d'offres_QWEN.bpmn"
```

The command creates or updates the private Kaggle script kernel, submits it with a Tesla T4 accelerator, and pauses the durable workflow.

Expected status:

```json
{
  "status": "waiting_for_llm",
  "run_id": "run_...",
  "interpretation_mode": "qwen3_kaggle"
}
```

The first Kaggle run may take longer because Qwen3-8B must be downloaded and loaded.

## 4. Check the Kaggle run

```powershell
uv run bpmn-agent agent-llm-status "run_..."
```

Wait until the returned state is `complete`.

## 5. Fetch and validate Qwen's interpretation

```powershell
uv run bpmn-agent agent-resume `
  "run_..." `
  --fetch-llm
```

The local code then:

1. verifies that the downloaded output belongs to the same `run_id` and request hash;
2. rejects unknown fields and any BPMN identifiers returned by the model;
3. maps `process_1`, `process_2`, and similar aliases to real process IDs locally;
4. passes only validated hints to the deterministic planner.

The next status will normally be either:

```text
needs_clarification
```

or:

```text
waiting_for_approval
```

## 6. Resolve ambiguity when requested

For example:

```powershell
uv run bpmn-agent agent-resume `
  "run_..." `
  --process-id "Id_54e28588-82ab-4392-a9be-a85620d80a90"
```

The workflow recomputes the deterministic checksummed plan without rerunning Qwen.

## 7. Approve and execute

```powershell
uv run bpmn-agent agent-resume `
  "run_..." `
  --approved
```

The source BPMN is never overwritten.

## Safety boundaries

Qwen3-8B receives only:

- the user's instruction;
- visible process aliases;
- participant names;
- lane names;
- visible element labels and BPMN types;
- process and lane counts.

It does not receive the original XML or real BPMN identifiers.

The accepted model output contains only:

```json
{
  "schema_version": "1.0",
  "operation": "insert_task_before",
  "target_query": "Rédiger le cahier des charges",
  "new_name": "Valider le dossier d'appel d'offres",
  "lane_name": "SPCM",
  "process_alias": null,
  "requires_clarification": true,
  "clarification_question": "Quelle variante du processus faut-il modifier ?",
  "confidence": 0.88
}
```

The model cannot approve execution, generate usable BPMN IDs, or modify XML.

## Inference configuration

The generated Kaggle worker uses:

```text
model: Qwen/Qwen3-8B
thinking mode: disabled
quantization: 4-bit NF4 with nested quantization
compute dtype: float16
accelerator: NvidiaTeslaT4
max new tokens: 384
```

The local laptop performs only orchestration, validation, planning, approval, and file editing.

## Manual output fallback

When Kaggle completes but automatic fetching is unavailable:

```powershell
uv run kaggle kernels output `
  "<your-kaggle-username>/bpmn-qwen3-interpreter" `
  -p ".\qwen_output" `
  -o
```

Then resume with:

```powershell
uv run bpmn-agent agent-resume `
  "run_..." `
  --llm-result-file ".\qwen_output\llm_interpretation.json"
```
