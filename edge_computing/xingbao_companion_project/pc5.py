# -*- coding: utf-8 -*-
"""
PC 少儿陪伴语音对话程序 - 自动监听低延迟版 v6

功能：
    电脑麦克风常驻监听 -> VAD 检测人声并自动截句 -> 2 秒内播放本地/缓存占位声音
    -> 百炼 Qwen3-ASR HTTP 识别 -> 百炼 Qwen 大模型回复
    -> 百炼 CosyVoice WebSocket 实时 TTS -> 电脑音响播放

特点：
    1. 回复语音使用 WebSocket 实时流，不下载临时音频 URL。
    2. 自动探测 Clash/代理端口：7897 -> 7892 -> 7890 -> 直连。
    3. VAD 自动监听：听到人声开始录，说完自动送云端。
    4. 2 秒硬指标：检测到说话结束后，立即播放预缓存/本地占位声音，云端慢也不会“没反应”。
    5. 单文件运行，便于在 Windows PC 上调试项目语音闭环。

安装依赖：
    python -m pip install -U requests sounddevice numpy

使用：
    1) 在环境变量 DASHSCOPE_API_KEY 中配置你的百炼 API Key
    2) python -u pc_child_companion_auto_proxy_v6.py --test-net
    3) python -u pc_child_companion_auto_proxy_v6.py --test-tts "你好，我是星宝。"
    4) python -u pc_child_companion_auto_proxy_v6.py --test-vad
    5) python -u pc_child_companion_auto_proxy_v6.py --once
"""

from __future__ import annotations

import argparse
import base64
import builtins
import json
import os
import queue
import shutil
import subprocess
import sys
import time
import wave
from collections import deque
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.settings import AppSettings
from core.voice_profiles import VoiceProfile
from multimodal.audio_io import RealtimeStreamingSpeechPlayer

# 让 Windows CMD / VSCode 里实时打印，不要“看起来卡死”
print = partial(builtins.print, flush=True)

# ==========================
# 你主要改这里
# ==========================

# 仅为占位符；运行时仅从 DASHSCOPE_API_KEY 环境变量读取真实密钥。
DASHSCOPE_API_KEY_IN_CODE = "YOUR_DASHSCOPE_API_KEY"

# 代理设置：AUTO 表示自动测试本机常见 Clash 端口。
# 你的电脑当前 netstat 显示 7892 和 7897 正在监听，所以默认优先测 7897，再测 7892。
PROXY_MODE = "auto"  # 可选："auto" / "none" / "manual"
MANUAL_PROXY = "http://127.0.0.1:7897"
AUTO_PROXY_CANDIDATES = [
    "http://127.0.0.1:7897",
    "http://127.0.0.1:7892",
    "http://127.0.0.1:7890",
    "",  # 最后尝试直连
]

# 音频设备：None 表示使用系统默认麦克风/扬声器。若有多个设备，可用 --list-devices 查看编号后填写整数。
INPUT_DEVICE: Optional[int] = None
OUTPUT_DEVICE: Optional[int] = None

# 少儿陪伴角色设定
ROLE_NAME = "星宝"
ROLE_IDENTITY = "住在智能陪伴桌里的小星球机器人"
CHILD_NAME = "小朋友"
CHILD_AGE_RANGE = "3-8岁"

# 百炼模型配置
ASR_MODEL = "qwen3-asr-flash"
LLM_MODEL = "qwen-plus"
TTS_MODEL = "cosyvoice-v3-flash"
TTS_VOICE = "longanyang"  # 可尝试：longxiaochun / longwan / longxiaoxia 等

# 录音配置
RECORD_SECONDS = 5
RECORD_SAMPLE_RATE = 16000
RECORD_CHANNELS = 1
SILENCE_RMS_THRESHOLD = 80  # 旧版固定录音静音判定；自动监听主要用下面 VAD 参数

# 自动监听 / VAD 配置
# 说明：本程序的“2 秒硬指标”定义为：检测到孩子说完话后，2 秒内必须先发出声音。
# 如果云端 ASR/LLM/TTS 来不及，就先播放 QUICK_ACK_TEXT 的缓存语音或本地提示音拖住。
VAD_FRAME_MS = 30
VAD_CALIBRATE_SECONDS = 0.6
VAD_PRE_ROLL_MS = 300
VAD_START_HOLD_MS = 120
VAD_END_SILENCE_MS = 750
VAD_MIN_UTTERANCE_MS = 500
VAD_MAX_UTTERANCE_SECONDS = 10
VAD_THRESHOLD_MULTIPLIER = 3.0
VAD_MIN_RMS = 180.0
VAD_END_THRESHOLD_RATIO = 0.62

# 2 秒内占位回复：启动时优先用百炼 TTS 缓存一句角色语音；失败则自动用本地提示音。
QUICK_ACK_TEXT = "星宝收到啦，我想一想。"
USE_CLOUD_ACK_CACHE = True

# 回复配置
MAX_REPLY_CHARS = 140
MAX_HISTORY_TURNS = 6

# 工作目录
WORK_DIR = Path("work_pc_companion")
INPUT_WAV = WORK_DIR / "input.wav"
REPLY_WAV = WORK_DIR / "reply.wav"
VAD_INPUT_WAV = WORK_DIR / "vad_input.wav"
QUICK_ACK_WAV = WORK_DIR / "quick_ack_cloud.wav"
CHIME_ACK_WAV = WORK_DIR / "quick_ack_chime.wav"

# 百炼 HTTP 接口
BAILIAN_COMPAT_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
BAILIAN_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"

# ==========================
# 工具函数
# ==========================

_SELECTED_PROXIES: Optional[Dict[str, str]] = None
_SELECTED_PROXY_LABEL: Optional[str] = None
_AUDIO_PLAY_LOCK = threading.Lock()
_ACK_WAV_PATH: Optional[Path] = None


def get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "没有找到 DASHSCOPE_API_KEY。\n"
            "请在终端设置 DASHSCOPE_API_KEY 环境变量。"
        )
    return key


def proxy_dict(proxy: str) -> Dict[str, str]:
    if not proxy:
        return {}
    return {"http": proxy, "https": proxy}


def import_requests():
    try:
        import requests  # type: ignore
        return requests
    except Exception as e:
        raise RuntimeError("缺少 requests，请先运行：python -m pip install -U requests") from e


def import_audio_libs():
    try:
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore
        return np, sd
    except Exception as e:
        raise RuntimeError("缺少音频依赖，请先运行：python -m pip install -U sounddevice numpy") from e


def select_proxies(force: bool = False) -> Dict[str, str]:
    """自动选择可用代理。返回 requests 可用的 proxies 字典。"""
    global _SELECTED_PROXIES, _SELECTED_PROXY_LABEL
    if _SELECTED_PROXIES is not None and not force:
        return _SELECTED_PROXIES

    requests = import_requests()

    if PROXY_MODE == "none":
        _SELECTED_PROXIES = {}
        _SELECTED_PROXY_LABEL = "直连"
        return _SELECTED_PROXIES

    if PROXY_MODE == "manual":
        _SELECTED_PROXIES = proxy_dict(MANUAL_PROXY)
        _SELECTED_PROXY_LABEL = MANUAL_PROXY or "直连"
        return _SELECTED_PROXIES

    candidates = AUTO_PROXY_CANDIDATES[:]

    # 如果用户终端已经设置了代理，也加入候选
    for env_name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(env_name, "").strip()
        if val and val not in candidates:
            candidates.insert(0, val)

    print("[net] 自动探测代理端口：" + " -> ".join([c if c else "直连" for c in candidates]))

    headers = {"Authorization": "Bearer dummy", "Content-Type": "application/json"}
    for cand in candidates:
        proxies = proxy_dict(cand)
        label = cand or "直连"
        try:
            # 用 GET/HEAD 都可能被接口拒绝，但只要能返回 HTTP 状态码，就说明网络链路通。
            resp = requests.get(
                "https://dashscope.aliyuncs.com",
                headers=headers,
                proxies=proxies,
                timeout=6,
                verify=True,
            )
            print(f"[net] 测试 {label} -> HTTP {resp.status_code}")
            if resp.status_code < 500:
                _SELECTED_PROXIES = proxies
                _SELECTED_PROXY_LABEL = label
                print(f"[net] 已选择网络通道：{label}")
                return _SELECTED_PROXIES
        except Exception as e:
            print(f"[net] 测试 {label} 失败：{e}")

    # 所有测试失败时，最后仍返回 7897，方便错误信息明确。
    fallback = AUTO_PROXY_CANDIDATES[0]
    _SELECTED_PROXIES = proxy_dict(fallback)
    _SELECTED_PROXY_LABEL = fallback
    print(f"[net] 没有探测到可用通道，临时使用：{fallback}")
    return _SELECTED_PROXIES


def request_json(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
    retries: int = 3,
) -> Dict[str, Any]:
    requests = import_requests()
    proxies = select_proxies()
    last_error: Optional[Exception] = None

    for i in range(1, retries + 1):
        try:
            if method.upper() == "POST":
                resp = requests.post(url, headers=headers, json=payload, proxies=proxies, timeout=timeout)
            elif method.upper() == "GET":
                resp = requests.get(url, headers=headers, proxies=proxies, timeout=timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")

            text_preview = resp.text[:800] if resp.text else ""
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code}: {text_preview}")
            try:
                return resp.json()
            except Exception as e:
                raise RuntimeError(f"接口没有返回 JSON：{text_preview}") from e
        except Exception as e:
            last_error = e
            print(f"[net] 第 {i}/{retries} 次请求失败：{e}")
            if i < retries:
                time.sleep(1.0)
                # 失败时重新探测一次代理，防止 Clash 端口状态变化
                select_proxies(force=True)

    raise RuntimeError(
        f"网络请求失败：{url}\n"
        f"最后错误：{last_error}\n"
        f"当前代理：{_SELECTED_PROXY_LABEL} / {_SELECTED_PROXIES}\n"
        "建议：确认 Clash 正在运行，并确认 7897 或 7892 是 HTTP/Mixed 代理端口。"
    )


def download_file(url: str, out_path: Path, timeout: int = 120) -> None:
    requests = import_requests()
    proxies = select_proxies()
    last_error: Optional[Exception] = None
    for i in range(1, 4):
        try:
            with requests.get(url, proxies=proxies, timeout=timeout, stream=True) as resp:
                if not resp.ok:
                    raise RuntimeError(f"下载失败 HTTP {resp.status_code}: {resp.text[:300]}")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return
        except Exception as e:
            last_error = e
            print(f"[download] 第 {i}/3 次下载失败：{e}")
            if i < 3:
                time.sleep(1.0)
                select_proxies(force=True)
    raise RuntimeError(f"音频下载失败：{url}\n最后错误：{last_error}")


def audio_to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "wav"
    mime = "wav" if suffix == "wav" else suffix
    return f"data:audio/{mime};base64,{b64}"


def clip_text(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "……"


# ==========================
# 音频录制与播放
# ==========================


def list_devices() -> None:
    _np, sd = import_audio_libs()
    print(sd.query_devices())
    print("\n[提示] 如果默认设备不对，修改程序顶部 INPUT_DEVICE / OUTPUT_DEVICE 为对应编号。")


def record_wav(path: Path = INPUT_WAV, seconds: int = RECORD_SECONDS) -> Tuple[Path, float]:
    np, sd = import_audio_libs()
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[录音] 开始录音 {seconds}s，请对着电脑麦克风说话……")
    audio = sd.rec(
        int(seconds * RECORD_SAMPLE_RATE),
        samplerate=RECORD_SAMPLE_RATE,
        channels=RECORD_CHANNELS,
        dtype="int16",
        device=INPUT_DEVICE,
    )
    sd.wait()
    audio = np.asarray(audio, dtype=np.int16)
    rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) if audio.size else 0.0

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(RECORD_CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RECORD_SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    print(f"[录音] 已保存：{path}，RMS={rms:.1f}")
    return path, rms


def play_wav(path: Path) -> None:
    """阻塞播放 WAV。加锁避免“占位声音”和“正式回复”同时播放。"""
    np, sd = import_audio_libs()
    if not path.exists():
        raise FileNotFoundError(path)

    with _AUDIO_PLAY_LOCK:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if sampwidth == 2:
            audio = np.frombuffer(frames, dtype=np.int16)
            audio_float = audio.astype(np.float32) / 32768.0
        elif sampwidth == 1:
            audio = np.frombuffer(frames, dtype=np.uint8)
            audio_float = (audio.astype(np.float32) - 128.0) / 128.0
        elif sampwidth == 4:
            audio = np.frombuffer(frames, dtype=np.int32)
            audio_float = audio.astype(np.float32) / 2147483648.0
        else:
            raise RuntimeError(f"暂不支持的 WAV 采样宽度：{sampwidth} bytes")

        if channels > 1:
            audio_float = audio_float.reshape(-1, channels)

        print(f"[播放] {path}，rate={rate}, channels={channels}")
        sd.play(audio_float, samplerate=rate, device=OUTPUT_DEVICE)
        sd.wait()

def local_tts_windows(text: str) -> None:
    """Windows 本地兜底朗读，不依赖云端 TTS。"""
    safe = text.replace("'", "''")
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Speak('{safe}');",
    ]
    subprocess.run(cmd, check=False)



# ==========================
# 自动监听 / 低延迟占位回复
# ==========================


def generate_chime_wav(path: Path, sample_rate: int = 24000) -> Path:
    """生成一个本地提示音，完全不依赖网络，用来保证 2 秒内先有声音。"""
    np, _sd = import_audio_libs()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 1000:
        return path

    # 一个柔和的“双音提示音”，总长约 0.62s。
    parts = []
    for freq, dur, amp in [(660, 0.16, 0.23), (0, 0.05, 0.0), (880, 0.22, 0.20), (0, 0.19, 0.0)]:
        n = int(sample_rate * dur)
        if freq <= 0:
            y = np.zeros(n, dtype=np.float32)
        else:
            t = np.arange(n, dtype=np.float32) / sample_rate
            y = amp * np.sin(2 * np.pi * freq * t)
            # 淡入淡出，避免爆音
            fade = max(1, int(sample_rate * 0.025))
            y[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            y[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        parts.append(y)
    audio = np.concatenate(parts)
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    print(f"[ack] 已生成本地占位提示音：{path}")
    return path


def prepare_quick_ack(args: argparse.Namespace) -> Path:
    """准备“2 秒内先出声”的占位音频。优先使用缓存的云端角色语音，失败就用本地提示音。"""
    global _ACK_WAV_PATH
    if _ACK_WAV_PATH is not None and _ACK_WAV_PATH.exists():
        return _ACK_WAV_PATH

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    generate_chime_wav(CHIME_ACK_WAV)

    if not args.no_cloud_ack_cache and USE_CLOUD_ACK_CACHE:
        if QUICK_ACK_WAV.exists() and QUICK_ACK_WAV.stat().st_size > 1000:
            _ACK_WAV_PATH = QUICK_ACK_WAV
            print(f"[ack] 使用已缓存的角色占位语音：{QUICK_ACK_WAV}")
            return _ACK_WAV_PATH
        try:
            print(f"[ack] 正在缓存占位语音：{QUICK_ACK_TEXT}")
            bailian_tts(QUICK_ACK_TEXT, QUICK_ACK_WAV)
            _ACK_WAV_PATH = QUICK_ACK_WAV
            print(f"[ack] 已缓存角色占位语音：{QUICK_ACK_WAV}")
            return _ACK_WAV_PATH
        except Exception as e:
            print(f"[ack] 云端占位语音缓存失败，改用本地提示音：{e}")

    _ACK_WAV_PATH = CHIME_ACK_WAV
    return _ACK_WAV_PATH


def play_quick_ack_async(args: argparse.Namespace, deadline_start: float) -> threading.Thread:
    """非阻塞播放占位声音，尽量在 2 秒内启动。"""
    ack_path = prepare_quick_ack(args)

    def _worker() -> None:
        delay = time.perf_counter() - deadline_start
        print(f"[latency] 占位声音启动延迟：{delay:.3f}s（目标 < 2.000s）")
        try:
            play_wav(ack_path)
        except Exception as e:
            print(f"[ack] 占位声音播放失败：{e}")

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    return th


def frame_rms_bytes(frame: bytes) -> float:
    np, _sd = import_audio_libs()
    if not frame:
        return 0.0
    arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr ** 2)))


def save_frames_to_wav(path: Path, frames: List[bytes], sample_rate: int = RECORD_SAMPLE_RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(RECORD_CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))
    return path


def capture_utterance_vad(args: argparse.Namespace, out_path: Path = VAD_INPUT_WAV) -> Tuple[Path, Dict[str, float]]:
    """常驻监听一次人声：检测到说话开始录，检测到静音结束截句。"""
    np, sd = import_audio_libs()
    frame_samples = int(RECORD_SAMPLE_RATE * VAD_FRAME_MS / 1000)
    q: "queue.Queue[bytes]" = queue.Queue(maxsize=200)

    def callback(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
        if status:
            # 不要刷屏，只在严重卡顿时提示
            pass
        try:
            q.put_nowait(bytes(indata))
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(bytes(indata))
            except Exception:
                pass

    print("[listen] 正在监听人声，说话后会自动截句……")
    print("[listen] 提示：如果误触发多，就调高 --vad-min-rms；如果叫不醒，就调低。")

    with sd.RawInputStream(
        samplerate=RECORD_SAMPLE_RATE,
        blocksize=frame_samples,
        channels=RECORD_CHANNELS,
        dtype="int16",
        device=INPUT_DEVICE,
        callback=callback,
    ):
        # 环境噪声校准
        calib_frames = max(1, int(VAD_CALIBRATE_SECONDS * 1000 / VAD_FRAME_MS))
        noise_values = []
        for _ in range(calib_frames):
            frame = q.get()
            noise_values.append(frame_rms_bytes(frame))
        noise = float(np.median(noise_values)) if noise_values else 0.0

        if args.vad_threshold > 0:
            start_threshold = float(args.vad_threshold)
        else:
            start_threshold = max(float(args.vad_min_rms), noise * float(args.vad_multiplier))
        end_threshold = max(float(args.vad_min_rms) * 0.55, start_threshold * VAD_END_THRESHOLD_RATIO)

        print(f"[vad] noise={noise:.1f}, start_threshold={start_threshold:.1f}, end_threshold={end_threshold:.1f}")

        pre_roll_max = max(1, int(VAD_PRE_ROLL_MS / VAD_FRAME_MS))
        start_hold_frames = max(1, int(VAD_START_HOLD_MS / VAD_FRAME_MS))
        end_silence_frames = max(1, int(VAD_END_SILENCE_MS / VAD_FRAME_MS))
        min_frames = max(1, int(VAD_MIN_UTTERANCE_MS / VAD_FRAME_MS))
        max_frames = max(1, int(args.max_utterance_seconds * 1000 / VAD_FRAME_MS))

        pre_roll: deque[bytes] = deque(maxlen=pre_roll_max)
        active_frames: List[bytes] = []
        voice_hold = 0
        silence_hold = 0
        speaking = False
        speech_start_perf = 0.0

        while True:
            frame = q.get()
            rms = frame_rms_bytes(frame)

            if not speaking:
                pre_roll.append(frame)
                if rms >= start_threshold:
                    voice_hold += 1
                else:
                    voice_hold = 0

                if voice_hold >= start_hold_frames:
                    speaking = True
                    speech_start_perf = time.perf_counter()
                    active_frames = list(pre_roll)
                    silence_hold = 0
                    print(f"[vad] 检测到人声，开始录制…… RMS={rms:.1f}")
                continue

            active_frames.append(frame)
            frame_count = len(active_frames)

            if rms < end_threshold:
                silence_hold += 1
            else:
                silence_hold = 0

            if frame_count >= max_frames:
                print("[vad] 达到最长句子时长，自动截断。")
                break

            if frame_count >= min_frames and silence_hold >= end_silence_frames:
                break

        utterance_ms = len(active_frames) * VAD_FRAME_MS
        save_frames_to_wav(out_path, active_frames)
        speech_end_perf = time.perf_counter()
        print(f"[vad] 句子结束，已保存：{out_path}，时长≈{utterance_ms/1000:.2f}s")
        return out_path, {
            "utterance_ms": float(utterance_ms),
            "speech_start_perf": speech_start_perf,
            "speech_end_perf": speech_end_perf,
            "start_threshold": float(start_threshold),
            "end_threshold": float(end_threshold),
            "noise": float(noise),
        }


def auto_one_turn(args: argparse.Namespace) -> bool:
    wav_path, info = capture_utterance_vad(args, VAD_INPUT_WAV)

    # 2 秒硬指标：检测到说话结束后立刻出一个占位声音。云端慢也不能让孩子感觉“没反应”。
    deadline_start = time.perf_counter()
    if not args.no_quick_ack and not args.no_tts:
        play_quick_ack_async(args, deadline_start)

    user_text = bailian_asr(wav_path)
    if not user_text:
        print("[提示] ASR 没有识别到文字，跳过本轮。")
        return True

    if any(w in user_text for w in EXIT_WORDS):
        reply = "好呀，那星宝先休息一下。下次我们再一起聊天、讲故事、玩小游戏！"
        print(f"[{ROLE_NAME}] {reply}")
        speak(reply, no_tts=args.no_tts, local_fallback=args.local_tts_fallback)
        return False

    reply = bailian_llm(user_text)
    speak(reply, no_tts=args.no_tts, local_fallback=args.local_tts_fallback)
    total = time.perf_counter() - deadline_start
    print(f"[latency] 从说话结束到正式回复播放完成：{total:.2f}s；2 秒内已由占位声音响应。")
    return True


def run_auto_loop(args: argparse.Namespace) -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print_startup(args)
    select_proxies(force=True)
    if not args.no_tts and not args.no_quick_ack:
        prepare_quick_ack(args)

    greeting = f"你好呀，我是{ROLE_NAME}！我会一直听着你。你说完后，星宝会先马上出声回应，再认真想答案。"
    if not args.no_greeting:
        print(f"[{ROLE_NAME}] {greeting}")
        speak(greeting, no_tts=args.no_tts, local_fallback=args.local_tts_fallback)

    if args.once:
        auto_one_turn(args)
        return 0

    while True:
        if not auto_one_turn(args):
            break
    return 0

# ==========================
# 百炼 ASR / LLM / TTS
# ==========================


def bailian_asr(wav_path: Path) -> str:
    api_key = get_api_key()
    data_uri = audio_to_data_uri(wav_path)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ASR_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "stream": False,
        "asr_options": {
            "language": "zh",
            "enable_itn": True,
        },
    }
    print(f"[asr] 调用 {ASR_MODEL} 识别：{wav_path}")
    data = request_json("POST", BAILIAN_COMPAT_CHAT_URL, headers=headers, payload=payload, timeout=90)
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"ASR 返回格式异常：{json.dumps(data, ensure_ascii=False)[:1200]}")
    text = (text or "").strip()
    print(f"[你] {text}")
    return text


def build_system_prompt() -> str:
    return f"""
你叫{ROLE_NAME}，身份是“{ROLE_IDENTITY}”。你正在和一个{CHILD_AGE_RANGE}的孩子进行语音陪伴对话。

你的目标：
1. 用温暖、活泼、简短、适合儿童听懂的话回应。
2. 每次回复尽量不超过{MAX_REPLY_CHARS}个中文字符。
3. 多鼓励孩子表达、观察、思考，可以提出一个小问题或小游戏。
4. 不询问家庭住址、电话、学校班级等隐私。
5. 不输出恐怖、暴力、成人化、危险操作内容。
6. 如果孩子提到身体不舒服、受伤、危险行为，要温柔提醒马上告诉爸爸妈妈、老师或身边大人。
7. 你不是医生、老师或监护人，不替代成年人照护。
8. 语气要像儿童陪伴桌里的角色，不要像客服，不要长篇说教。
""".strip()


CONVERSATION: List[Dict[str, str]] = []


def bailian_llm(user_text: str) -> str:
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 保留最近几轮上下文
    recent_history = CONVERSATION[-MAX_HISTORY_TURNS * 2 :]
    messages = [{"role": "system", "content": build_system_prompt()}] + recent_history
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0.75,
        "max_tokens": 220,
    }
    print(f"[llm] 调用 {LLM_MODEL} 思考……")
    data = request_json("POST", BAILIAN_COMPAT_CHAT_URL, headers=headers, payload=payload, timeout=90)
    try:
        reply = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"LLM 返回格式异常：{json.dumps(data, ensure_ascii=False)[:1200]}")

    reply = clip_text(reply, MAX_REPLY_CHARS)
    CONVERSATION.append({"role": "user", "content": user_text})
    CONVERSATION.append({"role": "assistant", "content": reply})
    print(f"[{ROLE_NAME}] {reply}")
    return reply


def bailian_tts(text: str, out_wav: Path = REPLY_WAV) -> Path:
    """HTTP synthesis is retained only to prebuild the local quick-ack cache."""
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": TTS_MODEL,
        "input": {
            "text": text,
            "voice": TTS_VOICE,
            "format": "wav",
            "sample_rate": 24000,
            "volume": 70,
            "rate": 1.0,
        },
    }
    print(f"[tts-cache] 缓存 {TTS_MODEL}/{TTS_VOICE} 到本地 WAV")
    data = request_json("POST", BAILIAN_TTS_URL, headers=headers, payload=payload, timeout=120)
    try:
        audio_url = data["output"]["audio"]["url"]
    except Exception:
        raise RuntimeError(f"TTS 返回格式异常：{json.dumps(data, ensure_ascii=False)[:1200]}")

    if not audio_url:
        raise RuntimeError(f"TTS 没有返回 audio.url：{json.dumps(data, ensure_ascii=False)[:1200]}")

    print("[tts-cache] 获取音频 URL 成功，正在下载缓存……")
    download_file(audio_url, out_wav)
    return out_wav


def speak(text: str, no_tts: bool = False, local_fallback: bool = False) -> None:
    if no_tts:
        return
    try:
        # pc5 keeps a standalone API-key setting.  Expose it to the common
        # WebSocket player, which otherwise reads the normal project setting.
        os.environ.setdefault("DASHSCOPE_API_KEY", get_api_key())
        settings = AppSettings.load()
        profile = VoiceProfile(
            id="pc5_realtime",
            label="PC 星宝",
            model=TTS_MODEL,
            voice=TTS_VOICE,
        )
        player = RealtimeStreamingSpeechPlayer(
            settings=settings,
            voice_profile=profile,
            output_device=OUTPUT_DEVICE,
        )
        print(f"[tts-ws] WebSocket 流式播放 {TTS_MODEL}/{TTS_VOICE}")
        player.start()
        player.enqueue(text)
        player.close()
    except Exception as e:
        if local_fallback and sys.platform.startswith("win"):
            print(f"[tts] 云端 TTS 失败，改用 Windows 本地朗读：{e}")
            local_tts_windows(text)
        else:
            raise


# ==========================
# 主流程
# ==========================

EXIT_WORDS = ["退出", "结束", "停止", "再见", "拜拜", "不聊了"]


def one_turn(args: argparse.Namespace) -> bool:
    wav_path, rms = record_wav(INPUT_WAV, seconds=args.record_seconds)
    if rms < args.silence_threshold:
        print(f"[提示] 声音太小或没有检测到说话，RMS={rms:.1f}，跳过本轮。")
        return True

    user_text = bailian_asr(wav_path)
    if not user_text:
        print("[提示] ASR 没有识别到文字，跳过本轮。")
        return True

    if any(w in user_text for w in EXIT_WORDS):
        reply = "好呀，那星宝先休息一下。下次我们再一起聊天、讲故事、玩小游戏！"
        print(f"[{ROLE_NAME}] {reply}")
        speak(reply, no_tts=args.no_tts, local_fallback=args.local_tts_fallback)
        return False

    reply = bailian_llm(user_text)
    speak(reply, no_tts=args.no_tts, local_fallback=args.local_tts_fallback)
    return True


def print_startup(args: argparse.Namespace) -> None:
    print("[启动] 少儿陪伴语音程序已启动。")
    print("[说明] 说“退出/结束/停止/再见”可结束；Ctrl+C 也可结束。")
    if getattr(args, "fixed_loop", False):
        print(f"[配置] 模式=固定录音轮询，录音={args.record_seconds}s")
    else:
        print("[配置] 模式=VAD自动监听，人声触发，句尾自动截断")
        print(f"[配置] 2秒硬指标=说话结束后立即播放占位声音：{QUICK_ACK_TEXT}")
    print(f"[配置] 角色={ROLE_NAME}，ASR={ASR_MODEL}，LLM={LLM_MODEL}")
    print(f"[配置] TTS=HTTP非实时 {TTS_MODEL}/{TTS_VOICE}，不使用 WebSocket")
    print(f"[配置] 自动代理候选={AUTO_PROXY_CANDIDATES}")


def run_loop(args: argparse.Namespace) -> int:
    if not args.fixed_loop:
        return run_auto_loop(args)

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print_startup(args)
    select_proxies(force=True)

    greeting = f"你好呀，我是{ROLE_NAME}！我住在这张会说话的小桌子里。你想和我聊天，还是玩一个小问题？"
    if not args.no_greeting:
        print(f"[{ROLE_NAME}] {greeting}")
        speak(greeting, no_tts=args.no_tts, local_fallback=args.local_tts_fallback)

    if args.once:
        one_turn(args)
        return 0

    while True:
        if not one_turn(args):
            break
    return 0


# ==========================
# 命令行
# ==========================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PC 少儿陪伴语音对话程序 - 阿里云百炼 v6 自动监听低延迟版")
    p.add_argument("--list-devices", action="store_true", help="列出电脑麦克风/扬声器设备")
    p.add_argument("--test-net", action="store_true", help="测试百炼 HTTP 网络通道和代理端口")
    p.add_argument("--test-record", action="store_true", help="测试固定录音并保存到 work_pc_companion/input.wav")
    p.add_argument("--test-vad", action="store_true", help="测试自动监听/VAD，听你说一句后自动保存 work_pc_companion/vad_input.wav")
    p.add_argument("--test-asr", action="store_true", help="录音后测试 ASR")
    p.add_argument("--test-llm", type=str, default="", help="测试大模型回复，例如 --test-llm 你好")
    p.add_argument("--test-tts", type=str, default="", help="测试 TTS 和播放，例如 --test-tts 你好")
    p.add_argument("--once", action="store_true", help="只进行一轮语音对话")
    p.add_argument("--fixed-loop", action="store_true", help="使用旧版固定时长录音轮询；默认是 VAD 自动监听")
    p.add_argument("--no-greeting", action="store_true", help="启动时不播放开场白")
    p.add_argument("--no-tts", action="store_true", help="不调用 TTS，只打印文字回复")
    p.add_argument("--local-tts-fallback", action="store_true", help="云端 TTS 失败时用 Windows 本地朗读兜底")
    p.add_argument("--no-quick-ack", action="store_true", help="关闭 2 秒内占位声音")
    p.add_argument("--no-cloud-ack-cache", action="store_true", help="不预先缓存云端占位语音，只使用本地提示音")
    p.add_argument("--record-seconds", type=int, default=RECORD_SECONDS, help="固定录音模式每轮录音秒数")
    p.add_argument("--silence-threshold", type=float, default=SILENCE_RMS_THRESHOLD, help="旧版固定录音静音判定 RMS 阈值")
    p.add_argument("--vad-threshold", type=float, default=0.0, help="手动指定 VAD 起始阈值；0 表示自动根据环境噪声估计")
    p.add_argument("--vad-min-rms", type=float, default=VAD_MIN_RMS, help="VAD 最小起始 RMS 阈值；误触发就调高，叫不醒就调低")
    p.add_argument("--vad-multiplier", type=float, default=VAD_THRESHOLD_MULTIPLIER, help="VAD 环境噪声倍率")
    p.add_argument("--max-utterance-seconds", type=float, default=VAD_MAX_UTTERANCE_SECONDS, help="一句话最长录制秒数")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if args.list_devices:
            list_devices()
            return 0

        if args.test_net:
            print("[test-net] 开始测试代理/网络……")
            proxies = select_proxies(force=True)
            print(f"[test-net] 最终选择：{_SELECTED_PROXY_LABEL} / {proxies}")
            # 顺便用 dummy key 确认 TTS 接口能返回 HTTP 状态，而不是连接失败
            requests = import_requests()
            resp = requests.get(BAILIAN_TTS_URL, proxies=proxies, timeout=10)
            print(f"[test-net] TTS URL GET -> HTTP {resp.status_code}")
            print("[test-net] 如果这里是 401/405/404 都可以，说明网络链路通；真正调用时会带 API Key。")
            return 0

        if args.test_record:
            record_wav(INPUT_WAV, seconds=args.record_seconds)
            print(f"[test-record] 录音文件：{INPUT_WAV.resolve()}")
            return 0

        if args.test_vad:
            capture_utterance_vad(args, VAD_INPUT_WAV)
            print(f"[test-vad] VAD 录音文件：{VAD_INPUT_WAV.resolve()}")
            return 0

        if args.test_asr:
            record_wav(INPUT_WAV, seconds=args.record_seconds)
            bailian_asr(INPUT_WAV)
            return 0

        if args.test_llm:
            select_proxies(force=True)
            bailian_llm(args.test_llm)
            return 0

        if args.test_tts:
            select_proxies(force=True)
            print(f"[{ROLE_NAME}] {args.test_tts}")
            speak(args.test_tts, no_tts=False, local_fallback=args.local_tts_fallback)
            return 0

        return run_loop(args)

    except KeyboardInterrupt:
        print("\n[退出] 用户中断。")
        return 0
    except Exception as e:
        print("\n[ERROR] 程序运行失败：")
        print(e)
        print("\n排查建议：")
        print("1. python -m pip install -U requests sounddevice numpy")
        print("2. python -u pc_child_companion_auto_proxy_v6.py --test-net")
        print("3. python -u pc_child_companion_auto_proxy_v6.py --list-devices")
        print("4. python -u pc_child_companion_auto_proxy_v6.py --test-record")
        print("5. python -u pc_child_companion_auto_proxy_v6.py --test-asr")
        print("6. python -u pc_child_companion_auto_proxy_v6.py --test-llm \"你好\"")
        print("7. python -u pc_child_companion_auto_proxy_v6.py --test-tts \"你好，我是星宝。\"")
        print("8. 如果代理仍失败，打开 Clash Verge 确认 HTTP/Mixed Port，再改程序顶部 MANUAL_PROXY 并把 PROXY_MODE 改为 'manual'。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
