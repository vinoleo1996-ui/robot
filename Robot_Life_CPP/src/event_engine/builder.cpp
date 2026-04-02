#include "robot_life_cpp/event_engine/builder.hpp"

#include <algorithm>
#include <cctype>

#include "robot_life_cpp/common/contracts.hpp"

namespace robot_life_cpp::event_engine {

EventBuilder::EventBuilder(
    std::unordered_map<std::string, common::EventPriority> event_priorities)
    : event_priorities_(std::move(event_priorities)) {}

common::RawEvent EventBuilder::build(
    const common::DetectionResult& detection,
    std::optional<common::EventPriority> priority,
    int ttl_ms) const {
  const auto canonical_type = canonical_event_type(detection.event_type);
  const auto canonical_detected = common::contracts::canonical_event_detected(canonical_type);

  common::EventPriority resolved = priority.value_or(common::EventPriority::P2);
  if (!priority.has_value()) {
    auto it = event_priorities_.find(canonical_detected);
    if (it == event_priorities_.end()) {
      it = event_priorities_.find(canonical_type);
    }
    if (it != event_priorities_.end()) {
      resolved = it->second;
    } else {
      resolved = default_event_priority(canonical_detected);
    }
  }

  common::RawEvent event{};
  event.event_id = common::new_id();
  event.trace_id = detection.trace_id;
  event.event_type = canonical_detected;
  event.priority = resolved;
  event.timestamp_monotonic = common::now_mono();
  event.confidence = detection.confidence;
  event.source = detection.detector;
  event.ttl_ms = ttl_ms;
  const auto target_it = detection.payload.find("target_id");
  const auto cooldown_target = target_it == detection.payload.end() ? canonical_type : target_it->second;
  event.cooldown_key = canonical_type + ":" + cooldown_target;
  event.payload = detection.payload;
  event.payload.emplace("event_confidence", std::to_string(detection.confidence));
  event.payload.emplace("raw_event_type", detection.event_type);
  return event;
}

std::string EventBuilder::canonical_event_type(const std::string& event_type) {
  const auto canonical_detected = common::contracts::canonical_event_detected(event_type);
  const std::string suffix = "_detected";
  if (canonical_detected.size() > suffix.size() &&
      canonical_detected.substr(canonical_detected.size() - suffix.size()) == suffix) {
    return canonical_detected.substr(0, canonical_detected.size() - suffix.size());
  }
  return canonical_detected;
}

common::EventPriority EventBuilder::default_event_priority(const std::string& event_type) {
  return common::contracts::default_event_priority(event_type);
}

}  // namespace robot_life_cpp::event_engine
