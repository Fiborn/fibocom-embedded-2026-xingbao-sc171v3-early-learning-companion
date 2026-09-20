"""Session orchestration for Xingbao Companion."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.action_bus import ActionBus
from core.conversation_history import ConversationHistoryStore
from core.memory import MemoryManager
from core.parent_summary import ParentSummaryManager
from intelligence.profile_extractor import ProfileExtractor
from intelligence.prompt_builder import PromptBuilder


DEFAULT_TEXT_DEMO_INPUT = "hello"
TEXT_DEMO_REPLY = (
    "星宝文本演示正在运行。真实聊天、语音、记忆和动作会在后续阶段接入。"
)


@dataclass
class SessionTurn:
    """A single text-mode turn captured by the session layer."""

    user_text: str
    assistant_text: str
    action: dict[str, str]


@dataclass
class SessionManager:
    """Coordinates companion turns without binding to voice or hardware yet."""

    history: list[SessionTurn] = field(default_factory=list)
    memory_manager: MemoryManager = field(default_factory=MemoryManager)
    action_bus: ActionBus = field(default_factory=ActionBus)
    prompt_builder: PromptBuilder | None = None
    profile_extractor: ProfileExtractor = field(default_factory=ProfileExtractor)
    conversation_history_store: ConversationHistoryStore | None = None
    parent_summary_manager: ParentSummaryManager | None = None

    def __post_init__(self) -> None:
        data_dir = self.memory_manager.path.parent
        if self.conversation_history_store is None:
            self.conversation_history_store = ConversationHistoryStore(
                data_dir / "conversation_history.json"
            )
        if self.parent_summary_manager is None:
            self.parent_summary_manager = ParentSummaryManager(
                data_dir / "parent_summaries.json"
            )
        if self.prompt_builder is None:
            self.prompt_builder = PromptBuilder(
                memory_manager=self.memory_manager,
                conversation_history_store=self.conversation_history_store,
                parent_summary_manager=self.parent_summary_manager,
            )

    def run_text_turn(self, user_text: str = DEFAULT_TEXT_DEMO_INPUT) -> SessionTurn:
        """Run one placeholder text turn.

        Phase 2 keeps this deterministic so the CLI can be tested without API
        keys, microphone access, speaker output, or hardware devices.
        """
        normalized_text = user_text.strip() or DEFAULT_TEXT_DEMO_INPUT
        return self.record_assistant_turn(
            user_text=normalized_text,
            assistant_text=TEXT_DEMO_REPLY,
            action_proposal={
                "screen_expression": "smile",
            },
        )

    def record_assistant_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        action_proposal: dict[str, str] | str | None = None,
    ) -> SessionTurn:
        """Record a completed assistant turn and apply safe profile updates."""
        normalized_text = user_text.strip() or DEFAULT_TEXT_DEMO_INPUT
        profile_result = self.profile_extractor.extract(normalized_text)
        if profile_result.updates:
            self.memory_manager.update(profile_result.updates)

        turn = SessionTurn(
            user_text=normalized_text,
            assistant_text=assistant_text.strip(),
            action=self.action_bus.emit(action_proposal).as_dict(),
        )
        self.history.append(turn)
        assert self.conversation_history_store is not None
        try:
            self.conversation_history_store.append_turn(
                child_text=turn.user_text,
                xingbao_text=turn.assistant_text,
            )
        except OSError:
            # A read-only or temporarily unavailable data disk must not break chat.
            pass
        return turn

    def as_chat_history(self) -> list[dict[str, str]]:
        """Return conversation history in chat-completions format."""
        messages: list[dict[str, str]] = []
        for turn in self.history:
            messages.append({"role": "user", "content": turn.user_text})
            messages.append({"role": "assistant", "content": turn.assistant_text})
        return messages

    def run_text_demo(self) -> str:
        """Return a printable placeholder transcript for the text demo."""
        turn = self.run_text_turn()
        assert self.prompt_builder is not None
        prompt_preview = self.prompt_builder.build_system_prompt().splitlines()[0]
        return (
            f"User: {turn.user_text}\n"
            f"Xingbao: {turn.assistant_text}\n"
            f"Action: {turn.action}\n"
            f"Prompt preview: {prompt_preview}"
        )
