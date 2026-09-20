#!/usr/bin/env sh
set -eu

# Terminal 1:
#   cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge
#   python3 desktop.py --fullscreen --low-effects
#
# Terminal 2:
#   cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
#   export DASHSCOPE_API_KEY="your_key_here"
#   sh deploy/board_start_demo.sh

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
COMPANION_DIR="${XINGBAO_COMPANION_DIR:-$(dirname -- "$SCRIPT_DIR")}"

cd "$COMPANION_DIR"

PYTHON_BIN="/usr/bin/python3"
ENV_FILE="${XINGBAO_ENV_FILE:-$HOME/.config/xingbao/runtime.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

# The board is configured for direct cloud access.  DashScope's streaming ASR
# and TTS SDKs establish WebSockets independently of the HTTP client, so do
# not let a terminal or desktop-session proxy leak into this child process.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
NO_PROXY='*'
no_proxy='*'
export NO_PROXY no_proxy

# Read this after runtime.env so the board-specific USB microphone index is
# honored.  The fallback preserves the existing portable demo behavior.
INPUT_DEVICE="${XINGBAO_INPUT_DEVICE:-0}"

# The competition board's USB microphone is more reliable through ALSA than
# PortAudio.  Keep this board-only route in the environment so PCs retain the
# regular sounddevice path.
# Do not bind this to a numeric card index: after a cold boot the Qualcomm
# board codec is card 0 and the USB PnP microphone is card 1.  The ALSA card
# name is stable across their enumeration order, so it is safe for recovery
# starts as well as the normal competition boot path.
ALSA_INPUT_DEVICE="${XINGBAO_ALSA_INPUT_DEVICE:-plughw:CARD=Device,DEV=0}"
ALSA_INPUT_GAIN="${XINGBAO_ALSA_INPUT_GAIN:-4.0}"
# Persist the resolved defaults into the child process environment.  Merely
# exporting an unset XINGBAO_ALSA_INPUT_DEVICE would otherwise make the wake
# loop fall back to the lower-gain PortAudio route after a board reboot.
XINGBAO_ALSA_INPUT_DEVICE="$ALSA_INPUT_DEVICE"
XINGBAO_ALSA_INPUT_GAIN="$ALSA_INPUT_GAIN"
export XINGBAO_ALSA_INPUT_DEVICE XINGBAO_ALSA_INPUT_GAIN

# Use the bundled local openWakeWord model by default.  ASR remains an
# explicit diagnostic fallback only when XINGBAO_WAKE_BACKEND=asr is set.
XINGBAO_WAKE_BACKEND="${XINGBAO_WAKE_BACKEND:-kws}"
export XINGBAO_WAKE_BACKEND
# Single ASR mode switch, read by every startup entry.  `local` starts/reuses
# the bundled Sherpa service; `cloud` leaves it off to save board resources.
# Set it in runtime.env, for example: XINGBAO_ASR_BACKEND=local
XINGBAO_ASR_BACKEND="${XINGBAO_ASR_BACKEND:-cloud}"
case "$XINGBAO_ASR_BACKEND" in
  cloud|local) ;;
  *) echo "[xingbao] XINGBAO_ASR_BACKEND must be cloud or local" >&2; exit 2 ;;
esac
export XINGBAO_ASR_BACKEND
# Keep wake activation strict. A generic speech-activity fallback can be
# triggered by narration or speaker echo during a live presentation.
XINGBAO_ASR_WAKE_FALLBACK_ON_SPEECH="${XINGBAO_ASR_WAKE_FALLBACK_ON_SPEECH:-0}"
export XINGBAO_ASR_WAKE_FALLBACK_ON_SPEECH

# The board microphone has a higher idle RMS than a laptop microphone.  Keep
# a fixed wake-only RMS floor even when WebRTC supplies the speech decision:
# this rejects distant video narration without forcing the relative dialogue
# noise multiplier onto a short "星宝星宝".  These remain venue-tunable in
# runtime.env.
XINGBAO_ASR_WAKE_MANUAL_THRESHOLD="${XINGBAO_ASR_WAKE_MANUAL_THRESHOLD:-1500}"
XINGBAO_ASR_WAKE_MIN_UTTERANCE_MS="${XINGBAO_ASR_WAKE_MIN_UTTERANCE_MS:-420}"
XINGBAO_ASR_WAKE_WEBRTC_MIN_RMS="${XINGBAO_ASR_WAKE_WEBRTC_MIN_RMS:-1500}"
XINGBAO_ASR_WAKE_START_HOLD_MS="${XINGBAO_ASR_WAKE_START_HOLD_MS:-120}"
XINGBAO_ASR_WAKE_RMS_LOG_INTERVAL_MS="${XINGBAO_ASR_WAKE_RMS_LOG_INTERVAL_MS:-500}"
export XINGBAO_ASR_WAKE_MANUAL_THRESHOLD XINGBAO_ASR_WAKE_MIN_UTTERANCE_MS \
  XINGBAO_ASR_WAKE_WEBRTC_MIN_RMS XINGBAO_ASR_WAKE_START_HOLD_MS \
  XINGBAO_ASR_WAKE_RMS_LOG_INTERVAL_MS

case "$ALSA_INPUT_DEVICE" in
  plughw:[0-9]*,*|hw:[0-9]*,*)
    ALSA_INPUT_CARD="${ALSA_INPUT_DEVICE#*:}"
    ALSA_INPUT_CARD="${ALSA_INPUT_CARD%%,*}"
    if command -v amixer >/dev/null 2>&1; then
      amixer -q -c "$ALSA_INPUT_CARD" sset Mic 100% cap || true
    fi
    ;;
esac

VISION_ARG=""
VISION_HEALTH_ARGS=""
if [ "${XINGBAO_ENABLE_VISION:-1}" != "0" ]; then
  VISION_ARG="--vision-runtime"
  # Keep the main visual service lightweight by default: face distance and
  # FER+ emotion remain active, while YOLO object detection is paused.
  XINGBAO_VISION_NO_OBJECTS="${XINGBAO_VISION_NO_OBJECTS:-1}"
  XINGBAO_VISION_MODEL="${XINGBAO_VISION_MODEL:-$COMPANION_DIR/models/vision/yolo11n.pt}"
  # QCS6490 CPU profile: do not run MediaPipe and FER+ for every MJPEG frame.
  XINGBAO_VISION_WIDTH="${XINGBAO_VISION_WIDTH:-480}"
  XINGBAO_VISION_HEIGHT="${XINGBAO_VISION_HEIGHT:-360}"
  XINGBAO_VISION_TARGET_FPS="${XINGBAO_VISION_TARGET_FPS:-0}"
  XINGBAO_VISION_FACE_INTERVAL_SECONDS="${XINGBAO_VISION_FACE_INTERVAL_SECONDS:-0.125}"
  XINGBAO_VISION_EMOTION_INTERVAL_SECONDS="${XINGBAO_VISION_EMOTION_INTERVAL_SECONDS:-300}"
  XINGBAO_VISION_OBJECT_INTERVAL_SECONDS="${XINGBAO_VISION_OBJECT_INTERVAL_SECONDS:-1.0}"
  # The canonical multimodal vision process is also the only visualization
  # window. This prevents a second detector from disagreeing with reminders.
  XINGBAO_VISION_VISUALIZE="${XINGBAO_VISION_VISUALIZE:-1}"
  XINGBAO_VISION_ALWAYS_ON_TOP="${XINGBAO_VISION_ALWAYS_ON_TOP:-1}"
  export XINGBAO_VISION_NO_OBJECTS XINGBAO_VISION_MODEL XINGBAO_VISION_WIDTH XINGBAO_VISION_HEIGHT \
    XINGBAO_VISION_TARGET_FPS XINGBAO_VISION_FACE_INTERVAL_SECONDS XINGBAO_VISION_EMOTION_INTERVAL_SECONDS \
    XINGBAO_VISION_OBJECT_INTERVAL_SECONDS \
    XINGBAO_VISION_VISUALIZE XINGBAO_VISION_ALWAYS_ON_TOP
  if [ "${XINGBAO_REQUIRE_VISION:-0}" = "1" ]; then
    VISION_HEALTH_ARGS="--check-vision"
    if [ "$XINGBAO_VISION_NO_OBJECTS" = "1" ]; then
      VISION_HEALTH_ARGS="$VISION_HEALTH_ARGS --vision-no-objects"
    fi
  fi
fi

# A cold boot can make optional sound/UI probes temporarily slow.  Record the
# warning, but do not prevent the actual companion process from starting.
"$PYTHON_BIN" tools/board_health_check.py $VISION_HEALTH_ARGS \
  || echo "[xingbao] startup preflight deferred; continuing" >&2

PREWARM_ARG=""
if [ "${XINGBAO_PREPARE_GAME_TTS_CACHE:-1}" != "0" ]; then
  PREWARM_ARG="--prewarm-game-tts-cache"
fi

# The raw ALSA realtime PCM backend remains available for controlled hardware
# validation, but it is opt-in until the board's long-lived PCM device sharing
# is fully accepted.  The default keeps the proven WAV/aplay speech path free
# for wake acknowledgements, ordinary dialogue, and game audio.
REALTIME_TTS_ARG=""
if [ "${XINGBAO_ENABLE_REALTIME_TTS:-1}" = "1" ]; then
  REALTIME_TTS_ARG="--realtime-tts"
fi
# Keep realtime TTS for ordinary free conversation when enabled, but avoid
# opening a second cloud audio stream while the board is recording.  The
# scripted dinosaur and game lines are pre-cached WAVs, so this trades a small
# amount of free-chat latency for a much safer live audio path.
XINGBAO_REALTIME_TTS_PREWARM="${XINGBAO_REALTIME_TTS_PREWARM:-0}"
export XINGBAO_REALTIME_TTS_PREWARM

# Feed the rendered speaker PCM to WebRTC AEC3, then run the stricter TTS KWS
# detector on the echo-reduced microphone signal.  This never interrupts on
# ordinary speech: only the wake phrase can stop TTS.
XINGBAO_ENABLE_WEBRTC_AEC3=1
XINGBAO_AEC3_DELAY_MS="${XINGBAO_AEC3_DELAY_MS:-110}"
export XINGBAO_ENABLE_WEBRTC_AEC3 XINGBAO_AEC3_DELAY_MS

DEMO_FOLLOW_UP_TIMEOUT="${XINGBAO_DEMO_FOLLOW_UP_TIMEOUT:-30}"
# After wake acknowledgement, never leave the board recording forever when
# nobody continues speaking.  Follow-up turns still use the longer timeout
# above, so the scripted demonstration has enough time between lines.
DEMO_LISTEN_TIMEOUT="${XINGBAO_DEMO_LISTEN_TIMEOUT:-10}"
# Keep the normal noise-adaptive VAD when this is unset.  In a noisy venue the
# operator can set a calibrated positive RMS threshold in runtime.env instead
# of allowing the noise baseline to raise the dialogue gate too high.
DIALOGUE_VAD_MANUAL_THRESHOLD="${XINGBAO_DIALOGUE_VAD_MANUAL_THRESHOLD:-}"
DIALOGUE_VAD_ARG=""
if [ -n "$DIALOGUE_VAD_MANUAL_THRESHOLD" ]; then
  case "$DIALOGUE_VAD_MANUAL_THRESHOLD" in
    *[!0-9.]*|*.*.*|.)
      echo "[xingbao] invalid XINGBAO_DIALOGUE_VAD_MANUAL_THRESHOLD" >&2
      exit 2
      ;;
  esac
  if ! awk "BEGIN { exit !($DIALOGUE_VAD_MANUAL_THRESHOLD > 0 && $DIALOGUE_VAD_MANUAL_THRESHOLD <= 20000) }"; then
    echo "[xingbao] XINGBAO_DIALOGUE_VAD_MANUAL_THRESHOLD must be in (0, 20000]" >&2
    exit 2
  fi
  DIALOGUE_VAD_ARG="--vad-manual-threshold $DIALOGUE_VAD_MANUAL_THRESHOLD"
  echo "[xingbao] dialogue VAD uses calibrated threshold=$DIALOGUE_VAD_MANUAL_THRESHOLD" >&2
fi
# A 600 ms end window noticeably shortens the visible "listening" state while
# retaining room for a child's natural short pause. It remains adjustable per
# venue through runtime.env without a source-code change.
DIALOGUE_VAD_END_SILENCE_MS="${XINGBAO_DIALOGUE_VAD_END_SILENCE_MS:-600}"
case "$DIALOGUE_VAD_END_SILENCE_MS" in
  *[!0-9]*|'')
    echo "[xingbao] invalid XINGBAO_DIALOGUE_VAD_END_SILENCE_MS" >&2
    exit 2
    ;;
esac
if ! awk "BEGIN { exit !($DIALOGUE_VAD_END_SILENCE_MS >= 300 && $DIALOGUE_VAD_END_SILENCE_MS <= 1500) }"; then
  echo "[xingbao] XINGBAO_DIALOGUE_VAD_END_SILENCE_MS must be in [300, 1500]" >&2
  exit 2
fi
DIALOGUE_VAD_END_SILENCE_ARG="--vad-end-silence-ms $DIALOGUE_VAD_END_SILENCE_MS"
echo "[xingbao] dialogue VAD end silence=$DIALOGUE_VAD_END_SILENCE_MS ms" >&2
# Keep full per-turn diagnostics in the persistent voice log.  This records
# cloud ASR finalization, LLM/tool calls, and TTS failures with their precise
# error messages, which is essential for diagnosing an intermittent stalled
# answer on the board.
VOICE_EVENT_LOG_ARG=""
if [ "${XINGBAO_SHOW_VOICE_EVENTS:-1}" = "1" ]; then
  VOICE_EVENT_LOG_ARG="--show-voice-events"
fi
# The camera path is currently disabled on the board to keep CPU headroom.
# Preserve the reviewed multimodal-support wording only for the deterministic
# dinosaur demo script; this does not enable or emulate camera processing.
XINGBAO_DEMO_VISUAL_SUPPORT="${XINGBAO_DEMO_VISUAL_SUPPORT:-1}"
export XINGBAO_DEMO_VISUAL_SUPPORT

"$PYTHON_BIN" -u main.py \
  --wake-chat \
  --board-audio-output \
  $REALTIME_TTS_ARG \
  --streaming-asr \
  --board-ui \
  --game-speech \
  $VISION_ARG \
  $PREWARM_ARG \
  --input-device "$INPUT_DEVICE" \
  --follow-up-timeout "$DEMO_FOLLOW_UP_TIMEOUT" \
  --listen-timeout "$DEMO_LISTEN_TIMEOUT" \
  $DIALOGUE_VAD_ARG \
  $DIALOGUE_VAD_END_SILENCE_ARG \
  --low-latency-voice \
  $VOICE_EVENT_LOG_ARG \
  "$@"
