"""Tests for context-window budget tracking and compaction.

Per CLAUDE.md §4: context is a bounded resource like retries and step budgets. Every agent's
history is tracked against a token budget and compacted before it would overflow the model's
real context window.
"""

import pytest

from config.settings import Settings
from multiagent.context.manager import (
    ContextManager,
    Turn,
    estimate_tokens,
    llama_agent_token_budget,
    ollama_agent_token_budget,
)


def _char_counter(text: str) -> int:
    """1 'token' per character — makes the arithmetic in tests exact and easy to read."""
    return len(text)


def test_estimate_tokens_approximates_four_chars_per_token():
    assert estimate_tokens("") == 1  # never zero, an empty turn still costs something
    assert estimate_tokens("a" * 40) == 10


def test_llama_agent_token_budget_divides_ctx_size_across_parallel_slots():
    settings = Settings(_env_file=None, llama_context_size=8192, llama_parallel_slots=2)

    # 8192 / 2 slots = 4096 per slot, minus the 512-token response reserve
    assert llama_agent_token_budget(settings, response_reserve=512) == 3584


def test_ollama_agent_token_budget_subtracts_response_reserve():
    settings = Settings(_env_file=None, ollama_tool_context_size=4096)

    assert ollama_agent_token_budget(settings, response_reserve=256) == 3840


def test_add_turn_and_total_tokens_use_the_injected_counter():
    manager = ContextManager(max_tokens=100, token_counter=_char_counter)

    manager.add_turn("user", "hello")  # 5 chars
    manager.add_turn("assistant", "hi there")  # 8 chars

    assert manager.total_tokens() == 13
    assert manager.turns == (Turn(role="user", content="hello"), Turn(role="assistant", content="hi there"))


def test_should_warn_and_needs_compaction_respect_their_ratios():
    manager = ContextManager(
        max_tokens=100, warning_ratio=0.75, hard_ratio=0.9, token_counter=_char_counter
    )

    manager.add_turn("user", "x" * 70)
    assert manager.should_warn() is False
    assert manager.needs_compaction() is False

    manager.add_turn("user", "x" * 10)  # total 80 >= 75 warn threshold
    assert manager.should_warn() is True
    assert manager.needs_compaction() is False

    manager.add_turn("user", "x" * 15)  # total 95 >= 90 hard threshold
    assert manager.needs_compaction() is True


def test_evict_old_tool_output_keeps_only_the_most_recent_tool_turns():
    manager = ContextManager(max_tokens=1000, keep_recent_tool_turns=1, token_counter=_char_counter)
    manager.add_turn("user", "do something")
    manager.add_turn("tool", "first tool result, quite long output")
    manager.add_turn("assistant", "ok, next step")
    manager.add_turn("tool", "second tool result")

    manager.evict_old_tool_output()

    roles_and_contents = [(t.role, t.content) for t in manager.turns]
    assert roles_and_contents[0] == ("user", "do something")
    assert roles_and_contents[1] == ("tool", "[tool output omitted to save context]")
    assert roles_and_contents[2] == ("assistant", "ok, next step")
    assert roles_and_contents[3] == ("tool", "second tool result")  # most recent kept verbatim


def test_evict_old_tool_output_is_idempotent():
    manager = ContextManager(max_tokens=1000, keep_recent_tool_turns=0, token_counter=_char_counter)
    manager.add_turn("tool", "some result")

    manager.evict_old_tool_output()
    manager.evict_old_tool_output()

    assert manager.turns[0].content == "[tool output omitted to save context]"


def test_compact_collapses_old_turns_into_one_summary_turn():
    manager = ContextManager(max_tokens=1000, keep_recent_turns=1, token_counter=_char_counter)
    manager.add_turn("user", "turn one")
    manager.add_turn("assistant", "turn two")
    manager.add_turn("user", "turn three")

    captured_old_turns = []

    def fake_summarizer(old_turns):
        captured_old_turns.extend(old_turns)
        return "summary of the earlier conversation"

    manager.compact(fake_summarizer)

    assert [t.content for t in captured_old_turns] == ["turn one", "turn two"]
    assert manager.turns[0] == Turn(role="summary", content="summary of the earlier conversation")
    assert manager.turns[1] == Turn(role="user", content="turn three")
    assert len(manager.turns) == 2


def test_compact_is_a_no_op_when_within_keep_recent_turns():
    manager = ContextManager(max_tokens=1000, keep_recent_turns=5, token_counter=_char_counter)
    manager.add_turn("user", "only turn")

    def failing_summarizer(_old_turns):
        raise AssertionError("summarizer should not be called")

    manager.compact(failing_summarizer)

    assert len(manager.turns) == 1


def test_maybe_compact_evicts_tool_output_first_and_skips_summary_if_that_is_enough():
    manager = ContextManager(
        max_tokens=100, hard_ratio=0.9, keep_recent_tool_turns=0, token_counter=_char_counter
    )
    manager.add_turn("tool", "x" * 95)  # over the hard threshold on its own

    def failing_summarizer(_old_turns):
        raise AssertionError("summarizer should not be called once eviction is enough")

    compacted = manager.maybe_compact(failing_summarizer)

    assert manager.turns[0].content == "[tool output omitted to save context]"
    assert compacted is False


def test_maybe_compact_falls_back_to_summarization_when_eviction_is_not_enough():
    manager = ContextManager(
        max_tokens=100, hard_ratio=0.9, keep_recent_turns=1, keep_recent_tool_turns=1, token_counter=_char_counter
    )
    manager.add_turn("user", "x" * 50)
    manager.add_turn("user", "y" * 50)  # non-tool turns, eviction alone can't help

    compacted = manager.maybe_compact(lambda _old_turns: "summary")

    assert compacted is True
    assert manager.turns[0].role == "summary"


def test_render_for_prompt_formats_turns_in_order():
    manager = ContextManager(max_tokens=1000, token_counter=_char_counter)
    manager.add_turn("user", "hello")
    manager.add_turn("assistant", "hi")

    assert manager.render_for_prompt() == "[user] hello\n[assistant] hi"


@pytest.mark.parametrize("bad_ratio", [0.0, 1.5])
def test_context_manager_rejects_out_of_range_ratios(bad_ratio):
    with pytest.raises(ValueError):
        ContextManager(max_tokens=100, warning_ratio=bad_ratio)
