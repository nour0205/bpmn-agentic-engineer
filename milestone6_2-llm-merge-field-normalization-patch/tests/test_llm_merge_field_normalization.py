from bpmn_agentic_engineer.llm.schema import LlmInterpretation


def test_merge_replacement_name_is_recovered_from_target_query() -> None:
    interpretation = LlmInterpretation.from_dict(
        {
            "schema_version": "1.1",
            "operation": "replace_linear_task_sequence",
            "target_query": "Automated consolidated task",
            "source_queries": ["Task A", "Task B", "Task C"],
            "new_bpmn_type": "serviceTask",
            "lane_name": "Actor lane",
            "process_alias": "process_1",
            "requires_clarification": False,
            "clarification_question": None,
            "confidence": 1.0,
        },
        allowed_process_aliases={"process_1"},
    )

    assert interpretation.new_name == "Automated consolidated task"
    assert interpretation.target_query is None
