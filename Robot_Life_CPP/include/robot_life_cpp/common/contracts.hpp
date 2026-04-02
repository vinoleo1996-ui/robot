#pragma once

#include <string>
#include <string_view>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::common::contracts {

inline constexpr std::string_view EVENT_FAMILIAR_FACE_DETECTED = "familiar_face_detected";
inline constexpr std::string_view EVENT_STRANGER_FACE_DETECTED = "stranger_face_detected";
inline constexpr std::string_view EVENT_GESTURE_DETECTED = "gesture_detected";
inline constexpr std::string_view EVENT_GAZE_SUSTAINED_DETECTED = "gaze_sustained_detected";
inline constexpr std::string_view EVENT_LOUD_SOUND_DETECTED = "loud_sound_detected";
inline constexpr std::string_view EVENT_COLLISION_WARNING_DETECTED = "collision_warning_detected";
inline constexpr std::string_view EVENT_EMERGENCY_STOP_DETECTED = "emergency_stop_detected";
inline constexpr std::string_view EVENT_MOTION_DETECTED = "motion_detected";
inline constexpr std::string_view EVENT_FACE_DETECTED = "face_detected";
inline constexpr std::string_view EVENT_FACE_IDENTITY_DETECTED = "face_identity_detected";
inline constexpr std::string_view EVENT_FACE_ATTENTION_DETECTED = "face_attention_detected";
inline constexpr std::string_view EVENT_POSE_DETECTED = "pose_detected";
inline constexpr std::string_view EVENT_WAVE_DETECTED = "wave_detected";
inline constexpr std::string_view EVENT_APPROACHING_DETECTED = "approaching_detected";
inline constexpr std::string_view EVENT_LEAVING_DETECTED = "leaving_detected";
inline constexpr std::string_view EVENT_SCENE_CONTEXT_DETECTED = "scene_context_detected";
inline constexpr std::string_view EVENT_PERSON_PRESENT_DETECTED = "person_present_detected";
inline constexpr std::string_view EVENT_OBJECT_DETECTED = "object_detected";

inline constexpr std::string_view BEHAVIOR_PERFORM_GREETING = "perform_greeting";
inline constexpr std::string_view BEHAVIOR_GREETING_VISUAL_ONLY = "greeting_visual_only";
inline constexpr std::string_view BEHAVIOR_PERFORM_ATTENTION = "perform_attention";
inline constexpr std::string_view BEHAVIOR_ATTENTION_MINIMAL = "attention_minimal";
inline constexpr std::string_view BEHAVIOR_PERFORM_GESTURE_RESPONSE = "perform_gesture_response";
inline constexpr std::string_view BEHAVIOR_GESTURE_VISUAL_ONLY = "gesture_visual_only";
inline constexpr std::string_view BEHAVIOR_PERFORM_SAFETY_ALERT = "perform_safety_alert";
inline constexpr std::string_view BEHAVIOR_PERFORM_TRACKING = "perform_tracking";

bool is_known_event_type(const std::string& event_type);
bool is_known_behavior_id(const std::string& behavior_id);
std::string canonical_event_detected(const std::string& event_type);
EventPriority default_event_priority(const std::string& event_type);

}  // namespace robot_life_cpp::common::contracts
