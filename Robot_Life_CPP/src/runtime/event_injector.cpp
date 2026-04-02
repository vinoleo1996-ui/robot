#include "robot_life_cpp/runtime/event_injector.hpp"

#include <algorithm>
#include <utility>

#include "robot_life_cpp/common/visual_contract.hpp"

namespace robot_life_cpp::runtime {

DetectionEventInjector::DetectionEventInjector(EventInjectorConfig config)
    : config_(std::move(config)) {
  if (config_.max_events_per_batch == 0) {
    config_.max_events_per_batch = 1;
  }
}

void DetectionEventInjector::reconfigure(EventInjectorConfig config) {
  if (config.max_events_per_batch == 0) {
    config.max_events_per_batch = 1;
  }
  config_ = std::move(config);
  last_emit_by_signature_.clear();
  last_emit_by_cooldown_key_.clear();
}

std::vector<common::RawEvent> DetectionEventInjector::build_events(
    const std::vector<common::DetectionResult>& detections,
    double now_mono) {
  std::vector<common::RawEvent> events{};
  events.reserve(std::min(detections.size(), config_.max_events_per_batch));

  for (const auto& detection : detections) {
    if (events.size() >= config_.max_events_per_batch) {
      break;
    }
    if (common::visual_contract::is_visual_event_type(detection.event_type)) {
      const auto validation = common::visual_contract::validate_visual_detection(detection);
      if (!validation.ok) {
        continue;
      }
    }
    auto event = builder_.build(detection);
    if (!should_emit(event, now_mono)) {
      continue;
    }
    events.push_back(std::move(event));
  }
  return events;
}

std::size_t DetectionEventInjector::inject_into(
    LiveLoop* loop,
    const std::vector<common::DetectionResult>& detections,
    double now_mono) {
  if (loop == nullptr) {
    return 0;
  }
  const auto events = build_events(detections, now_mono);
  for (const auto& event : events) {
    loop->ingest(event);
  }
  return events.size();
}

bool DetectionEventInjector::should_emit(const common::RawEvent& event, double now_mono) {
  const auto signature = dedupe_signature(event);
  if (const auto it = last_emit_by_signature_.find(signature);
      it != last_emit_by_signature_.end() && (now_mono - it->second) < config_.dedupe_window_s) {
    return false;
  }

  if (const auto it = last_emit_by_cooldown_key_.find(event.cooldown_key);
      it != last_emit_by_cooldown_key_.end() && (now_mono - it->second) < config_.cooldown_window_s) {
    return false;
  }

  last_emit_by_signature_[signature] = now_mono;
  last_emit_by_cooldown_key_[event.cooldown_key] = now_mono;
  return true;
}

std::string DetectionEventInjector::dedupe_signature(const common::RawEvent& event) {
  const auto track_it = event.payload.find("track_id");
  const auto frame_it = event.payload.find("frame_id");
  const auto track_id = track_it == event.payload.end() ? "unknown_track" : track_it->second;
  const auto frame_id = frame_it == event.payload.end() ? "unknown_frame" : frame_it->second;
  return event.event_type + "|" + event.source + "|" + track_id + "|" + frame_id;
}

}  // namespace robot_life_cpp::runtime
