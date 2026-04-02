#include "robot_life_cpp/common/visual_contract.hpp"

#include <algorithm>
#include <array>

namespace robot_life_cpp::common::visual_contract {

std::vector<std::string_view> required_visual_payload_keys() {
  return {KEY_CAMERA_ID, KEY_FRAME_ID, KEY_TRACK_ID, KEY_BBOX};
}

std::vector<std::string_view> optional_visual_payload_keys() {
  return {
      KEY_LANDMARKS,
      KEY_CLASS_NAME,
      KEY_EMBEDDING_REF,
      KEY_IDENTITY_STATE,
      KEY_ATTENTION_STATE,
      KEY_GESTURE_NAME,
      KEY_MOTION_SCORE,
      KEY_MOTION_DIRECTION,
      KEY_SCENE_TAGS,
      KEY_SCENE_HINT,
  };
}

bool is_visual_event_type(const std::string& event_type) {
  static const std::array<std::string_view, 12> kKnown{
      EVENT_FACE_DETECTED,          EVENT_FACE_IDENTITY_DETECTED, EVENT_FACE_ATTENTION_DETECTED,
      EVENT_POSE_DETECTED,          EVENT_GESTURE_DETECTED,       EVENT_WAVE_DETECTED,
      EVENT_MOTION_DETECTED,        EVENT_APPROACHING_DETECTED,   EVENT_LEAVING_DETECTED,
      EVENT_SCENE_CONTEXT_DETECTED, EVENT_PERSON_PRESENT_DETECTED, EVENT_OBJECT_DETECTED,
  };
  return std::find(kKnown.begin(), kKnown.end(), event_type) != kKnown.end();
}

DetectionValidationResult validate_visual_detection(const DetectionResult& detection) {
  DetectionValidationResult result{};

  if (detection.detector.empty()) {
    result.message = "detector is required";
    return result;
  }
  if (detection.source.empty()) {
    result.message = "source is required";
    return result;
  }
  if (!is_visual_event_type(detection.event_type)) {
    result.message = "unknown visual event type: " + detection.event_type;
    return result;
  }

  for (const auto key : required_visual_payload_keys()) {
    if (!detection.payload.contains(std::string(key)) || detection.payload.at(std::string(key)).empty()) {
      result.missing_required_keys.emplace_back(key);
    }
  }

  if (!result.missing_required_keys.empty()) {
    result.message = "missing required visual payload keys";
    return result;
  }

  result.ok = true;
  result.message = "ok";
  return result;
}

}  // namespace robot_life_cpp::common::visual_contract
