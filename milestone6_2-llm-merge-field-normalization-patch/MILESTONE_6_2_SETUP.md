# Milestone 6.2 — Qwen merge-field normalization

This patch fixes a narrow Qwen interpretation error for
`replace_linear_task_sequence`: when Qwen puts the replacement task label in
`target_query` and omits `new_name`, the local strict schema moves that label to
`new_name` and clears `target_query` before semantic validation.

It also strengthens the Qwen system prompt with an exact JSON example.

The correction is intentionally limited to `replace_linear_task_sequence`.
No BPMN IDs are accepted and no XML operation is inferred remotely.
