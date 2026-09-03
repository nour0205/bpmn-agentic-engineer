# BPMN Agentic Engineer

A safety-first BPMN 2.0 agent that turns a natural-language change request into a validated BPMN file—without allowing the language model to edit XML.

The supported product flow is:

```text
BPMN file + business request
        ↓
compact semantic BPMN context
        ↓
Qwen3-8B interpretation (Kaggle)
        ↓
deterministic grounding against real element/process/lane IDs
        ↓
clarification when ambiguous
        ↓
checksummed deterministic plan
        ↓
explicit human approval
        ↓
BPMN XML + sequence-flow + BPMN-DI execution on a copy
        ↓
independent structural validation
        ↓
one validated final BPMN
```

## Why this architecture

LLMs are useful for understanding business language, but they are not trusted to rewrite BPMN XML. Qwen returns a small structured interpretation. The local engine then resolves exact BPMN elements, rejects ambiguity and unsupported operations, constructs an auditable plan, and executes only that approved plan.

The source BPMN is never overwritten by default. Plans bind the source checksum to the proposed operations, and completed outputs must pass structural validation.

## Capabilities

The deterministic engine supports five operations:

| Operation | Effect |
|---|---|
| `insert_task_before` | Insert a task before an exact flow-node anchor |
| `insert_task_after` | Insert a task after an exact flow-node anchor |
| `rename_element` | Rename one grounded BPMN element |
| `remove_element` | Remove one eligible element and reconnect its linear flow |
| `replace_linear_task_sequence` | Replace consecutive tasks with one task |

Insertions and replacements update lane membership, incoming/outgoing references, sequence flows, and BPMN-DI shapes/edges. A `callActivity` may be an insertion anchor. Multi-process models retain explicit process scope: destination lane selection does not silently change the target process.

Unsupported or non-linear transformations fail before execution. Ambiguous labels produce candidates containing exact element, process, and lane information.

## Installation

Requirements:

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Kaggle CLI credentials for real Qwen interpretation

```powershell
git clone <repository-url>
cd bpmn-agentic-engineer-starter
uv sync --extra dev
```

The application dependencies include LangGraph, its SQLite checkpointer, and Kaggle. No browser or JavaScript runtime is required.

Configure Kaggle using its standard credentials. The default private kernel reference is `nourkouider05/bpmn-qwen3-interpreter`; override it with `--kaggle-kernel-ref owner/slug` or `BPMN_AGENT_KAGGLE_KERNEL`.

## CLI

### Validate

```powershell
uv run bpmn-agent validate ".\tests\fixtures\execution_process.bpmn"
```

Validation checks duplicate IDs, sequence-flow endpoints, incoming/outgoing references, lane references, BPMN-DI references, and required shapes for editable flow nodes. Success reports `valid_for_agentic_editing: true` and `error_count: 0`.

### Analyze

```powershell
uv run bpmn-agent analyze ".\tests\fixtures\execution_process.bpmn"
uv run bpmn-agent analyze ".\tests\fixtures\execution_process.bpmn" --json
```

Analysis is deterministic and read-only. It reports structural metrics and evidence-based findings; it does not invent process recommendations.

### Apply one or more recommendations

```powershell
uv run bpmn-agent change ".\tests\fixtures\execution_process.bpmn" `
  --request "Ajoutez une tâche utilisateur nommée 'Valider la demande' avant l'activité 'Rédiger le cahier des charges'."
```

The agent grounds each Qwen interpretation locally, asks for clarification when required, prints the exact plan, and asks for approval. Approved recommendations accumulate in one internal working model. Only after all requests are processed is one final file written to `generated/<original filename>`.

Repeat `--request` for a batch, or use `--requests-file requests.txt` with one recommendation per non-empty UTF-8 line:

```powershell
uv run bpmn-agent change process.bpmn `
  --request "Ajoutez un contrôle avant 'Publier le dossier'." `
  --request "Renommez 'Contrôler' en 'Valider'."
```

For a chosen output path:

```powershell
uv run bpmn-agent change process.bpmn `
  --request "Supprimez l'activité 'Saisir la demande'." `
  --output ".\generated\result.bpmn"
```

A non-interactive invocation never guesses or auto-approves: if clarification or approval cannot be collected, it stops safely without executing.

### Interactive session

```powershell
uv run bpmn-agent interactive ".\tests\fixtures\execution_process.bpmn"
```

Enter one natural-language request at each `bpmn>` prompt. Every approved recommendation updates only an internal working model. `:finish` validates the accumulated result and writes exactly one final BPMN; rejected or failed recommendations leave the working model unchanged.

Available session commands:

- `:status` — show source, final target, process scope, approved count, and validation
- `:history` — list approved logical operations, not temporary files
- `:reset` — discard working changes and return to the untouched source
- `:finish` — validate, write the final BPMN, and exit
- `:quit` — prompt to save when approved changes remain unsaved

An existing final path is never silently given a version suffix. The terminal asks before overwriting; use `--force` for explicit non-interactive replacement.

## Optimization recommendations

```powershell
uv run bpmn-agent recommend ".\data\bpmn\as_is\Suivi des commandes.bpmn"
uv run bpmn-agent recommend process.bpmn --goal "Réduire le travail manuel" --json
```

The deterministic analyzer first extracts structural and lexical evidence from the AS-IS BPMN. Qwen reasons over that compact evidence, and local validation rejects recommendations that cite nonexistent elements, incorrect lanes or processes, or unsupported execution mappings. Recommendations are ranked and displayed only; they are never applied automatically and no BPMN output is created.

CIBLE files, the dataset manifest, planted issues, and evaluation labels are never exposed to runtime recommendation generation. They are used only by the separate evaluation utility.

## Safety model

1. The parser builds the real process, lane, element, sequence-flow, and BPMN-DI indexes.
2. Compact context exposes aliases to Qwen rather than real BPMN IDs.
3. The LLM response is parsed and validated against a strict schema.
4. Grounding maps names and aliases back to local IDs; duplicates require clarification.
5. The planner allows only supported deterministic operations and attaches source/plan checksums.
6. Execution requires approval, rejects source overwrite and checksum changes, and writes a new file.
7. The output is independently reparsed and validated. Failed validation is never reported as success.

Durable workflow state lives in `.bpmn_agent/` and is ignored by Git. It supports Qwen waiting, clarification, approval, execution, and validation interrupts through one canonical LangGraph workflow.

## Python API

`BpmnChangeService` is the supported high-level facade:

```python
from bpmn_agentic_engineer.change_service import BpmnChangeService

service = BpmnChangeService()
result = service.run_change(
    "process.bpmn",
    "Renommez l'activité 'Contrôler la demande' en 'Valider la demande'.",
    clarification_handler=my_clarification_handler,
    approval_handler=my_approval_handler,
)
```

`BpmnTransformationSession` (also exported as `BpmnInteractiveSession`) owns the private working model and the single final publication boundary. Lower-level parser, planner, executor, and validator classes remain available for controlled integrations.

## Project structure

```text
src/bpmn_agentic_engineer/
├── agent/           LangGraph state, routing, nodes, persistence, and resume
├── analysis/        Deterministic read-only structural analysis
├── bpmn/            XML document model and process inspector
├── execution/       Approved XML, flow, lane, and BPMN-DI transformations
├── llm/             Compact context, Qwen worker, Kaggle bridge, and schemas
├── planning/        Deterministic parsing, grounding, clarification, and plans
├── validation/      Structural and BPMN-DI validation
├── change_service.py
├── cli.py
├── integrity.py
└── models.py

tests/
└── fixtures/        Small sanitized BPMN regression models

data/bpmn/as_is/     BPMN inputs supplied to the agent
data/bpmn/cible/     Optimized evaluation references; never agent inputs
data/bpmn/dataset_manifest.json  Hidden evaluation ground truth
docs/                Architecture rationale
```

Generated BPMNs, checkpoints, Kaggle jobs, logs, and temporary outputs are ignored and are not part of the source tree.

## Evaluation dataset

Files under `data/bpmn/as_is/` are deliberately degraded but structurally valid processes used as agent inputs. Their optimized references live under `data/bpmn/cible/` and are used only after execution for evaluation. `data/bpmn/dataset_manifest.json` records the intentional issues and expected operation families; it is evaluation ground truth and must never be included in LLM context.

Agent outputs belong under the ignored `generated/` directory, never inside either immutable dataset directory. See [docs/BPMN_DATASET.md](docs/BPMN_DATASET.md) for the concise case inventory.

## Testing

```powershell
uv run pytest -q
```

The default suite mocks external Qwen/Kaggle work where appropriate. It covers parsing, validation, analysis, schemas, normalization, grounding, ambiguity, process scope, planning, all supported operations, checksums, approval, execution, BPMN-DI, durable workflow state, atomic multi-change sessions, and final-output collisions.

A real Qwen smoke test requires Kaggle network access and credentials and is intentionally not part of the default suite.

## Current boundaries

- The project executes requested recommendations; it does not autonomously invent optimizations.
- Only the five documented deterministic operations are supported.
- Real Qwen interpretation depends on an authenticated Kaggle environment and may take several minutes.
- Structural validation is intentionally focused on safe agentic editing, not full BPMN XSD or execution-engine conformance.

## License

MIT
