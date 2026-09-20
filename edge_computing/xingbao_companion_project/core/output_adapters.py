"""Computer-side output adapters for Xingbao coordination rehearsals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OutputEvent:
    """One observable output-side event for debugging integration flow."""

    type: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "status": self.status,
            "payload": self.payload,
        }


@dataclass
class OutputTrace:
    """Collects UI, voice, and tool events from one coordinated turn."""

    events: list[OutputEvent] = field(default_factory=list)

    def emit(self, event_type: str, status: str, **payload: Any) -> OutputEvent:
        event = OutputEvent(type=event_type, status=status, payload=payload)
        self.events.append(event)
        return event

    def as_list(self) -> list[dict[str, Any]]:
        return [event.as_dict() for event in self.events]


class ScreenStateAdapter:
    """Records the screen/avatar state that the main UI should render."""

    def record(
        self,
        trace: OutputTrace,
        *,
        expression: str,
        screen_text: str,
        action: dict[str, str] | None,
        applied: bool,
    ) -> None:
        trace.emit(
            "ui.expression",
            "applied" if applied else "planned",
            expression=expression,
            screen_text=screen_text,
            action=action or {},
        )


class SpeechQueueAdapter:
    """Records the speech request before a real TTS backend is required."""

    def record(
        self,
        trace: OutputTrace,
        *,
        speak_text: str,
        tts_requested: bool,
        tts_played: bool,
        no_tts: bool,
        force_skip: bool = False,
    ) -> None:
        if force_skip or not tts_requested or not speak_text:
            status = "skipped"
        elif tts_played:
            status = "played"
        elif no_tts:
            status = "planned"
        else:
            status = "failed_or_unavailable"
        trace.emit(
            "voice.speak",
            status,
            speak_text=speak_text,
            tts_requested=tts_requested,
            tts_played=tts_played,
            no_tts=no_tts,
            force_skip=force_skip,
        )


class ToolLaunchAdapter:
    """Records tool launch requests separately from actually opening windows."""

    def record(
        self,
        trace: OutputTrace,
        *,
        target: str,
        request_status: str,
        launch_enabled: bool,
        launched: bool,
        message: str = "",
    ) -> None:
        if not target:
            return
        if launched:
            status = "launched"
        elif launch_enabled and request_status != "ready":
            status = "blocked"
        elif launch_enabled:
            status = "failed_or_unavailable"
        else:
            status = "planned"
        trace.emit(
            "tool.open",
            status,
            target=target,
            request_status=request_status,
            launch_enabled=launch_enabled,
            launched=launched,
            message=message,
        )


@dataclass(frozen=True)
class OutputAdapterSet:
    """Default adapters used by the desktop rehearsal runtime."""

    screen: ScreenStateAdapter = field(default_factory=ScreenStateAdapter)
    speech: SpeechQueueAdapter = field(default_factory=SpeechQueueAdapter)
    tool: ToolLaunchAdapter = field(default_factory=ToolLaunchAdapter)
