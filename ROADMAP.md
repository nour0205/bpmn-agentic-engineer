# Roadmap

The core product is deliberately narrow: execute user-supplied BPMN recommendations safely and reliably.

## Stable product scope

- [x] BPMN parsing, inspection, lanes, processes, and sequence-flow graph
- [x] compact aliased context for Qwen3-8B
- [x] Kaggle job preparation, polling, retrieval, and UTF-8 handling
- [x] strict interpretation schema and local alias resolution
- [x] deterministic grounding and ambiguity clarification
- [x] checksummed plans and explicit approval
- [x] copy-only XML execution and BPMN-DI updates
- [x] structural validation and execution diff
- [x] durable LangGraph interrupts and resume
- [x] one-shot and multi-recommendation sessions with one final output
- [x] process-scope safeguards for multi-process BPMNs

## Supported transformations

- [x] `insert_task_before`
- [x] `insert_task_after`
- [x] `rename_element`
- [x] `remove_element`
- [x] `replace_linear_task_sequence`

## Future reliability work

- [ ] broaden sanitized regression coverage for gateways and nested subprocesses
- [ ] add an opt-in authenticated Qwen/Kaggle smoke-test marker
- [ ] improve diagnostics for remote Kaggle quota and authentication failures
- [ ] evaluate BPMN XSD validation as an additional validation layer

Autonomous optimization generation and graphical user interfaces are outside the current scope.
