#include "robot_life_cpp/runtime/load_shedder.hpp"

#include <algorithm>

namespace robot_life_cpp::runtime {

RuntimeLoadShedder::RuntimeLoadShedder(LoadShedderConfig config) : config_(std::move(config)) {
  config_.warning_pending_events = std::max<std::size_t>(1, config_.warning_pending_events);
  config_.shed_pending_events = std::max(config_.warning_pending_events, config_.shed_pending_events);
  config_.warning_scene_candidates = std::max<std::size_t>(1, config_.warning_scene_candidates);
  config_.shed_scene_candidates = std::max(config_.warning_scene_candidates, config_.shed_scene_candidates);
  config_.warning_max_events_per_batch = std::max<std::size_t>(1, config_.warning_max_events_per_batch);
  config_.shed_max_events_per_batch = std::max<std::size_t>(1, std::min(config_.warning_max_events_per_batch,
                                                                         config_.shed_max_events_per_batch));
  config_.normal_preview_every_ticks = std::max(1, config_.normal_preview_every_ticks);
  config_.warning_preview_every_ticks = std::max(config_.normal_preview_every_ticks, config_.warning_preview_every_ticks);
  config_.shed_preview_every_ticks = std::max(config_.warning_preview_every_ticks, config_.shed_preview_every_ticks);
  config_.normal_telemetry_every_ticks = std::max(1, config_.normal_telemetry_every_ticks);
  config_.warning_telemetry_every_ticks =
      std::max(config_.normal_telemetry_every_ticks, config_.warning_telemetry_every_ticks);
  config_.shed_telemetry_every_ticks =
      std::max(config_.warning_telemetry_every_ticks, config_.shed_telemetry_every_ticks);
}

LoadShedderDecision RuntimeLoadShedder::decide(const LoadShedderInput& input) const {
  LoadShedderDecision decision{};
  decision.max_events_per_batch = std::max<std::size_t>(1, input.configured_max_events_per_batch);
  decision.preview_every_ticks = config_.normal_preview_every_ticks;
  decision.telemetry_every_ticks = config_.normal_telemetry_every_ticks;
  decision.preview_enabled = input.ui_enabled;

  if (input.runtime.pending_events >= config_.shed_pending_events ||
      input.runtime.scene_candidates_last_tick >= config_.shed_scene_candidates) {
    decision.pressure = LoadPressure::Shed;
    decision.max_events_per_batch = config_.shed_max_events_per_batch;
    decision.preview_every_ticks = config_.shed_preview_every_ticks;
    decision.telemetry_every_ticks = config_.shed_telemetry_every_ticks;
    decision.preview_enabled = input.ui_enabled && input.runtime.pending_events < (config_.shed_pending_events * 2U);
    decision.reason = "runtime_backlog";
    return decision;
  }

  if (input.runtime.pending_events >= config_.warning_pending_events ||
      input.runtime.scene_candidates_last_tick >= config_.warning_scene_candidates ||
      (input.backend.delivered_batches > 0 &&
       input.backend.delivered_detections >= input.backend.delivered_batches * 4U)) {
    decision.pressure = LoadPressure::Warning;
    decision.max_events_per_batch = config_.warning_max_events_per_batch;
    decision.preview_every_ticks = config_.warning_preview_every_ticks;
    decision.telemetry_every_ticks = config_.warning_telemetry_every_ticks;
    decision.reason = "elevated_load";
    return decision;
  }

  decision.reason = "normal";
  return decision;
}

std::string to_string(LoadPressure pressure) {
  switch (pressure) {
    case LoadPressure::Normal:
      return "normal";
    case LoadPressure::Warning:
      return "warning";
    case LoadPressure::Shed:
      return "shed";
  }
  return "normal";
}

}  // namespace robot_life_cpp::runtime
