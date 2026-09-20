"""In-process high-level action bus for Xingbao Companion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.action_safety import ActionSanitizer, SafeAction


@dataclass
class ActionBus:
    """Publishes sanitized actions without touching raw hardware."""

    sanitizer: ActionSanitizer = field(default_factory=ActionSanitizer)
    emitted_actions: list[SafeAction] = field(default_factory=list)

    def emit(self, proposal: SafeAction | dict[str, Any] | str | None) -> SafeAction:
        """Sanitize and record a high-level action proposal."""
        action = self.sanitizer.sanitize(proposal)
        self.emitted_actions.append(action)
        return action

    def last_action(self) -> SafeAction | None:
        if not self.emitted_actions:
            return None
        return self.emitted_actions[-1]
