"""Context-window budget tracking and compaction for every agent's conversation history.

Per CLAUDE.md §4: context is a bounded resource, like the retry and step budgets that already
guard the orchestrator loop. Each agent's conversation history is tracked against a token
budget and compacted *before* it would overflow the model's real context window, instead of
growing unbounded until a request starts failing.

This matters concretely on this hardware: llama-server is launched with `-c 8192 -np 2`, and
since the slot count is explicit (not "auto"), `--kv-unified` defaults to *off* for this build
(confirmed via `llama-server --help`) — meaning the 8192-token context is split evenly across
the 2 parallel slots, so the Planner and Coder agents each get roughly 4096 tokens of real
context, not 8192. `llama_agent_token_budget` below accounts for that split.

The orchestrator-level equivalent of an interactive `/compact` command is `maybe_compact()`:
called after every turn, it first evicts stale tool output, and only reaches for a full
summarization pass if that alone isn't enough.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from config.settings import Settings

_PLACEHOLDER = "[tool output omitted to save context]"


def estimate_tokens(text: str) -> int:
    """Cheap token-count approximation (~4 chars/token). Not exact — see REQUIREMENTS.md §6.

    An exact count would require a round trip to llama-server's /tokenize endpoint per turn,
    which isn't worth the extra hardware/latency cost just for budget bookkeeping.
    """
    return max(1, len(text) // 4)


def llama_agent_token_budget(settings: Settings, response_reserve: int = 512) -> int:
    """Usable history budget for one Planner/Coder slot on the shared llama-server context."""
    per_slot_ctx = settings.llama_context_size // max(settings.llama_parallel_slots, 1)
    return max(per_slot_ctx - response_reserve, 0)


def ollama_agent_token_budget(settings: Settings, response_reserve: int = 256) -> int:
    """Usable history budget for the Tool agent's Ollama context window."""
    return max(settings.ollama_tool_context_size - response_reserve, 0)


@dataclass(frozen=True)
class Turn:
    """One entry in an agent's conversation history."""

    role: str  # "user" | "assistant" | "tool" | "summary"
    content: str


class ContextManager:
    """Tracks one agent's conversation history against a token budget and compacts it on demand."""

    def __init__(
        self,
        max_tokens: int,
        keep_recent_turns: int = 4,
        keep_recent_tool_turns: int = 2,
        warning_ratio: float = 0.75,
        hard_ratio: float = 0.9,
        token_counter: Callable[[str], int] = estimate_tokens,
    ):
        if not (0.0 < warning_ratio <= 1.0):
            raise ValueError("warning_ratio must be in (0, 1]")
        if not (0.0 < hard_ratio <= 1.0):
            raise ValueError("hard_ratio must be in (0, 1]")
        self.max_tokens = max_tokens
        self.keep_recent_turns = keep_recent_turns
        self.keep_recent_tool_turns = keep_recent_tool_turns
        self.warning_ratio = warning_ratio
        self.hard_ratio = hard_ratio
        self.token_counter = token_counter
        self._turns: list[Turn] = []

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    def add_turn(self, role: str, content: str) -> None:
        self._turns.append(Turn(role=role, content=content))

    def total_tokens(self) -> int:
        return sum(self.token_counter(turn.content) for turn in self._turns)

    def should_warn(self) -> bool:
        return self.total_tokens() >= self.max_tokens * self.warning_ratio

    def needs_compaction(self) -> bool:
        return self.total_tokens() >= self.max_tokens * self.hard_ratio

    def evict_old_tool_output(self) -> None:
        """Replace tool-role turns beyond the most recent `keep_recent_tool_turns` with a placeholder."""
        tool_indexes = [i for i, turn in enumerate(self._turns) if turn.role == "tool"]
        keep = self.keep_recent_tool_turns
        stale_indexes = tool_indexes[:-keep] if keep > 0 else tool_indexes
        for i in stale_indexes:
            if self._turns[i].content != _PLACEHOLDER:
                self._turns[i] = Turn(role="tool", content=_PLACEHOLDER)

    def compact(self, summarizer: Callable[[Sequence[Turn]], str]) -> None:
        """Collapse everything except the most recent `keep_recent_turns` into one summary turn."""
        if len(self._turns) <= self.keep_recent_turns:
            return
        split_at = len(self._turns) - self.keep_recent_turns
        old_turns, recent_turns = self._turns[:split_at], self._turns[split_at:]
        summary_text = summarizer(old_turns)
        self._turns = [Turn(role="summary", content=summary_text), *recent_turns]

    def maybe_compact(self, summarizer: Callable[[Sequence[Turn]], str]) -> bool:
        """Evict stale tool output first; fall back to summarization if still over budget.

        Returns True if a summarization pass ran, False if eviction alone was enough (or nothing
        needed to happen at all).
        """
        self.evict_old_tool_output()
        if self.needs_compaction():
            self.compact(summarizer)
            return True
        return False

    def render_for_prompt(self) -> str:
        return "\n".join(f"[{turn.role}] {turn.content}" for turn in self._turns)
