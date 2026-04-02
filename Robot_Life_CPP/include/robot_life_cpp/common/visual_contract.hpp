#pragma once

#include <string>
#include <string_view>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::common::visual_contract {

inline constexpr std::string_view KEY_CAMERA_ID = "camera_id";
inline constexpr std::string_view KEY_FRAME_ID = "frame_id";
inline constexpr std::string_view KEY_TRACK_ID = "track_id";
inline constexpr std::string_view KEY_BBOX = "bbox";
inline constexpr std::string_view KEY_LANDMARKS = "landmarks";
inline constexpr std::string_view KEY_CLASS_NAME = "class_name";
inline constexpr std::string_view KEY_EMBEDDING_REF = "embedding_ref";
inline constexpr std::string_view KEY_IDENTITY_STATE = "identity_state";
inline constexpr std::string_view KEY_ATTENTION_STATE = "attention_state";
inline constexpr std::string_view KEY_GESTURE_NAME = "gesture_name";
inline constexpr std::string_view KEY_MOTION_SCORE = "motion_score";
inline constexpr std::string_view KEY_MOTION_DIRECTION = "motion_direction";
inline constexpr std::string_view KEY_SCENE_TAGS = "scene_tags";
inline constexpr std::string_view KEY_SCENE_HINT = "scene_hint";

inline constexpr std::string_view EVENT_FACE_DETECTED = "face_detected";
inline constexpr std::string_view EVENT_FACE_IDENTITY_DETECTED = "face_identity_detected";
inline constexpr std::string_view EVENT_FACE_ATTENTION_DETECTED = "face_attention_detected";
inline constexpr std::string_view EVENT_POSE_DETECTED = "pose_detected";
inline constexpr std::string_view EVENT_GESTURE_DETECTED = "gesture_detected";
inline constexpr std::string_view EVENT_WAVE_DETECTED = "wave_detected";
inline constexpr std::string_view EVENT_MOTION_DETECTED = "motion_detected";
inline constexpr std::string_view EVENT_APPROACHING_DETECTED = "approaching_detected";
inline constexpr std::string_view EVENT_LEAVING_DETECTED = "leaving_detected";
inline constexpr std::string_view EVENT_SCENE_CONTEXT_DETECTED = "scene_context_detected";
inline constexpr std::string_view EVENT_PERSON_PRESENT_DETECTED = "person_present_detected";
inline constexpr std::string_view EVENT_OBJECT_DETECTED = "object_detected";

struct DetectionValidationResult {
  bool ok{false};
  std::vector<std::string> missing_required_keys{};
  std::string message{};
};

std::vector<std::string_view> required_visual_payload_keys();
std::vector<std::string_view> optional_visual_payload_keys();
bool is_visual_event_type(const std::string& event_type);
DetectionValidationResult validate_visual_detection(const DetectionResult& detection);

}  // namespace robot_life_cpp::common::visual_contract
