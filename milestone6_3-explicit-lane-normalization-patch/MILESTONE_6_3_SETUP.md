# Milestone 6.3 — Explicit lane normalization

This patch adds a deterministic post-processing layer to the generated Kaggle worker.
When the request explicitly names a lane that exists in the supplied BPMN catalogue,
that canonical lane name overrides Qwen's guessed lane. It also preserves the earlier
merge-field normalization.

## Install

```powershell
Expand-Archive `
  -LiteralPath ".\milestone6_3-explicit-lane-normalization-patch.zip" `
  -DestinationPath "." `
  -Force

$patchRoot = ".\milestone6_3-explicit-lane-normalization-patch"

Copy-Item -Recurse -Force `
  "$patchRoot\src\bpmn_agentic_engineer\*" `
  ".\src\bpmn_agentic_engineer\"

Copy-Item -Recurse -Force `
  "$patchRoot\tests\*" `
  ".\tests\"
```

## Verify

```powershell
Get-ChildItem -Path ".\src", ".\tests" -Directory -Filter "__pycache__" -Recurse |
  Remove-Item -Recurse -Force

uv run pytest ".\tests\test_qwen_worker_normalization.py" -q
```

Expected: `3 passed`.
