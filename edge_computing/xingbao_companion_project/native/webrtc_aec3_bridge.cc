#include <cstdint>

#include "modules/audio_processing/include/audio_processing.h"

// A deliberately small C ABI: the Python runtime only has to exchange 10 ms
// mono PCM16 frames, while WebRTC's C++ API remains isolated here.
struct XingbaoAec3 {
  webrtc::AudioProcessing* apm;
  webrtc::StreamConfig config;
};

extern "C" XingbaoAec3* xingbao_aec3_create(int sample_rate_hz) {
  if (sample_rate_hz != 8000 && sample_rate_hz != 16000 &&
      sample_rate_hz != 32000 && sample_rate_hz != 48000) {
    return nullptr;
  }
  auto* state = new XingbaoAec3{webrtc::AudioProcessingBuilder().Create(),
                                webrtc::StreamConfig(sample_rate_hz, 1)};
  if (!state->apm) {
    delete state;
    return nullptr;
  }
  webrtc::AudioProcessing::Config config;
  // The current packaged WebRTC APM uses EchoCanceller3 for the desktop
  // echo-canceller path (mobile_mode=false).
  config.echo_canceller.enabled = true;
  config.echo_canceller.mobile_mode = false;
  config.high_pass_filter.enabled = true;
  config.noise_suppression.enabled = true;
  config.noise_suppression.level =
      webrtc::AudioProcessing::Config::NoiseSuppression::kHigh;
  state->apm->ApplyConfig(config);
  return state;
}

extern "C" void xingbao_aec3_destroy(XingbaoAec3* state) {
  if (!state) return;
  state->apm->Release();
  delete state;
}

extern "C" int xingbao_aec3_render(XingbaoAec3* state,
                                     const int16_t* input,
                                     int16_t* output) {
  if (!state || !input || !output) return -1;
  return state->apm->ProcessReverseStream(input, state->config, state->config,
                                           output);
}

extern "C" int xingbao_aec3_capture(XingbaoAec3* state,
                                      const int16_t* input,
                                      int16_t* output,
                                      int delay_ms) {
  if (!state || !input || !output) return -1;
  state->apm->set_stream_delay_ms(delay_ms);
  return state->apm->ProcessStream(input, state->config, state->config, output);
}
