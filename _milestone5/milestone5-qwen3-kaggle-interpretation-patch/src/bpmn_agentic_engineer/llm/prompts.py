from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You interpret BPMN change requests. Return exactly one JSON object and nothing else.

Allowed operations:
- insert_task_after
- insert_task_before
- rename_element
- remove_element
- unsupported

Required schema:
{
  "schema_version": "1.0",
  "operation": "...",
  "target_query": "visible BPMN label or null",
  "new_name": "visible new label or null",
  "lane_name": "visible actor/lane name or null",
  "process_alias": "process_N or null",
  "requires_clarification": true or false,
  "clarification_question": "one concise question or null",
  "confidence": 0.0 to 1.0
}

Safety rules:
1. Never invent or return BPMN IDs, element IDs, process IDs, lane IDs, or sequence-flow IDs.
2. Use only process aliases from the supplied catalogue.
3. If several processes contain the same plausible target and the request does not distinguish
   them, set process_alias to null and requires_clarification to true.
4. Do not silently choose between duplicate activities.
5. Preserve the user's requested task name; do not expand it into a recommendation.
6. The deterministic local planner will ground labels and perform all XML operations.
7. Use unsupported when the requested control-flow edit is outside the four allowed operations.
"""


def build_messages(request_text: str, context: dict[str, Any]) -> list[dict[str, str]]:
    user_payload = {
        "request": " ".join(request_text.split()),
        "bpmn_catalogue": context,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]
