#include "robot_life_cpp/common/contracts.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <unordered_map>

namespace robot_life_cpp::common::contracts {

namespace {
std::string normalize_event(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  const std::string suffix = "_detected";
  if (value.size() > suffix.size() &&
      value.substr(value.size() - suffix.size()) == suffix) {
    value.resize(value.size() - suffix.size());
  }
  return value;
}
}  // namespace

bool is_known_event_type(const std::string& event_type) {
  static const std::array<std::string_view, 18> kKnown{
      EVENT_FAMILIAR_FACE_DETECTED,
      EVENT_STRANGER_FACE_DETECTED,
      EVENT_GESTURE_DETECTED,
      EVENT_GAZE_SUSTAINED_DETECTED,
      EVENT_LOUD_SOUND_DETECTED,
      EVENT_COLLISION_WARNING_DETECTED,
      EVENT_EMERGENCY_STOP_DETECTED,
      EVENT_MOTION_DETECTED,
      EVENT_FACE_DETECTED,
      EVENT_FACE_IDENTITY_DETECTED,
      EVENT_FACE_ATTENTION_DETECTED,
      EVENT_POSE_DETECTED,
      EVENT_WAVE_DETECTED,
      EVENT_APPROACHING_DETECTED,
      EVENT_LEAVING_DETECTED,
      EVENT_SCENE_CONTEXT_DETECTED,
      EVENT_PERSON_PRESENT_DETECTED,
      EVENT_OBJECT_DETECTED,
  };
  return std::find(kKnown.begin(), kKnown.end(), event_type) != kKnown.end();
}

bool is_known_behavior_id(const std::string& behavior_id) {
  static const std::array<std::string_view, 8> kKnown{
      BEHAVIOR_PERFORM_GREETING,
      BEHAVIOR_GREETING_VISUAL_ONLY,
      BEHAVIOR_PERFORM_ATTENTION,
      BEHAVIOR_ATTENTION_MINIMAL,
      BEHAVIOR_PERFORM_GESTURE_RESPONSE,
      BEHAVIOR_GESTURE_VISUAL_ONLY,
      BEHAVIOR_PERFORM_SAFETY_ALERT,
      BEHAVIOR_PERFORM_TRACKING,
  };
  return std::find(kKnown.begin(), kKnown.end(), behavior_id) != kKnown.end();
}

std::string canonical_event_detected(const std::string& event_type) {
  const auto normalized = normalize_event(event_type);
  if (normalized.empty()) {
    return {};
  }
  if (normalized.rfind("gesture_", 0) == 0 || normalized == "hand_wave" || normalized == "wave") {
    return std::string(EVENT_GESTURE_DETECTED);
  }
  if (normalized == "person_present") {
    return std::string(EVENT_PERSON_PRESENT_DETECTED);
  }
  if (normalized == "scene_context" || normalized == "scene_tag") {
    return std::string(EVENT_SCENE_CONTEXT_DETECTED);
  }
  if (normalized == "gaze_hold" || normalized == "gaze_sustained" || normalized == "gaze_fixation") {
    return std::string(EVENT_GAZE_SUSTAINED_DETECTED);
  }
  return normalized + "_detected";
}

EventPriority default_event_priority(const std::string& event_type) {
  static const std::unordered_map<std::string, EventPriority> kPriorities{
      {std::string(EVENT_COLLISION_WARNING_DETECTED), EventPriority::P0},
      {std::string(EVENT_EMERGENCY_STOP_DETECTED), EventPriority::P0},
      {std::string(EVENT_LOUD_SOUND_DETECTED), EventPriority::P0},
      {std::string(EVENT_FAMILIAR_FACE_DETECTED), EventPriority::P1},
      {std::string(EVENT_FACE_DETECTED), EventPriority::P1},
      {std::string(EVENT_FACE_IDENTITY_DETECTED), EventPriority::P1},
      {std::string(EVENT_FACE_ATTENTION_DETECTED), EventPriority::P1},
      {std::string(EVENT_GESTURE_DETECTED), EventPriority::P1},
      {std::string(EVENT_WAVE_DETECTED), EventPriority::P1},
      {std::string(EVENT_POSE_DETECTED), EventPriority::P2},
      {std::string(EVENT_STRANGER_FACE_DETECTED), EventPriority::P2},
      {std::string(EVENT_GAZE_SUSTAINED_DETECTED), EventPriority::P2},
      {std::string(EVENT_SCENE_CONTEXT_DETECTED), EventPriority::P2},
      {std::string(EVENT_PERSON_PRESENT_DETECTED), EventPriority::P2},
      {std::string(EVENT_OBJECT_DETECTED), EventPriority::P2},
      {std::string(EVENT_APPROACHING_DETECTED), EventPriority::P1},
      {std::string(EVENT_LEAVING_DETECTED), EventPriority::P2},
      {std::string(EVENT_MOTION_DETECTED), EventPriority::P3},
  };
  const auto canonical = canonical_event_detected(event_type);
  const auto it = kPriorities.find(canonical);
  if (it == kPriorities.end()) {
    return EventPriority::P2;
  }
  return it->second;
}

}  // namespace robot_life_cpp::common::contracts
