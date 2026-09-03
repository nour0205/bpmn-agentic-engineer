# Architecture decision: LLM interpretation, deterministic BPMN execution

## Decision

The language model interprets business language but never reads or writes raw BPMN XML. All graph facts, target selection, planning, mutation, BPMN-DI updates, and validation remain deterministic and local.

## Canonical workflow

`BpmnChangeService` drives one durable LangGraph workflow:

1. parse and validate the source;
2. serialize compact aliased context;
3. submit Qwen3-8B interpretation through Kaggle;
4. validate the structured response;
5. ground it against real elements, lanes, and processes;
6. interrupt for clarification when the target is ambiguous;
7. build and checksum an allow-listed plan;
8. interrupt for explicit approval;
9. execute on a copy, including BPMN-DI;
10. independently parse and validate the output.

## Safety boundary

- Source BPMNs are not overwritten.
- Real BPMN IDs are not sent to the LLM.
- Equivalent labels in different processes do not permit silent process switching.
- Only supported deterministic operations can reach the executor.
- The approved plan checksum and source checksum are verified at execution time.
- Invalid generated BPMNs are reported as failures, never successful outputs.

LangGraph is retained because checkpointed interrupts and resume behavior are active product requirements. Runtime state is stored under ignored `.bpmn_agent/`.
