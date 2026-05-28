from advanced_agent.memory_alignment import LLMMemoryAlignment


class LabelModel:
    def chat(self, messages):
        return '{"semantic":"semantic label","methodology":"methodology label","decision":"decision label","agent_relevance":"relevance label"}'


class BadModel:
    def chat(self, messages):
        return 'not json'


def test_llm_memory_alignment_uses_json_labels() -> None:
    labels = LLMMemoryAlignment(LabelModel()).labels_for("architecture first", agent_role="main")
    assert labels["semantic"] == "semantic label"
    assert labels["methodology"] == "methodology label"


def test_llm_memory_alignment_falls_back_on_bad_json() -> None:
    labels = LLMMemoryAlignment(BadModel()).labels_for("architecture first", agent_role="main")
    assert "architecture first" in labels["semantic"]
