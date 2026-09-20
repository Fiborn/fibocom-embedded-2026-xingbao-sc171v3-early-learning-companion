"""DashScope HTTP TTS client."""

from __future__ import annotations

import threading
from pathlib import Path

from core.network import NetworkClient
from core.settings import AppSettings, get_dashscope_api_key
from core.voice_profiles import VoiceProfile


BAILIAN_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
DEFAULT_REPLY_WAV = Path("work/cache/reply.wav")


class DashScopeTTSClient:
    """Synthesizes speech through DashScope HTTP TTS."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        network_client: NetworkClient | None = None,
        voice_profile: VoiceProfile | None = None,
        *,
        request_timeout: int = 120,
        retries: int = 3,
        interrupt_event: threading.Event | None = None,
    ) -> None:
        self.settings = settings or AppSettings.load()
        self.network_client = network_client or NetworkClient(self.settings)
        self.voice_profile = voice_profile or VoiceProfile.from_settings(self.settings)
        self.request_timeout = max(1, int(request_timeout))
        self.retries = max(1, int(retries))
        self.interrupt_event = interrupt_event

    def synthesize(self, text: str, out_wav: Path | str = DEFAULT_REPLY_WAV) -> Path:
        if self.interrupt_event is not None and self.interrupt_event.is_set():
            raise RuntimeError("TTS synthesis cancelled.")
        api_key = get_dashscope_api_key()
        out_path = Path(out_wav)
        payload = {
            "model": self.voice_profile.model,
            "input": {
                "text": text,
                "voice": self.voice_profile.voice,
                "format": "wav",
                "sample_rate": self.voice_profile.sample_rate,
                "volume": self.voice_profile.volume,
                "rate": self.voice_profile.rate,
            },
        }
        data = self.network_client.request_json(
            "POST",
            BAILIAN_TTS_URL,
            headers=_auth_headers(api_key),
            payload=payload,
            timeout=self.request_timeout,
            retries=self.retries,
        )
        if self.interrupt_event is not None and self.interrupt_event.is_set():
            raise RuntimeError("TTS synthesis cancelled.")
        try:
            audio_url = str(data["output"]["audio"]["url"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Unexpected TTS response format.") from exc
        if not audio_url:
            raise RuntimeError("TTS response did not include an audio URL.")
        self.network_client.download_file(
            audio_url,
            out_path,
            timeout=self.request_timeout,
            retries=self.retries,
            interrupt_event=self.interrupt_event,
        )
        return out_path


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
