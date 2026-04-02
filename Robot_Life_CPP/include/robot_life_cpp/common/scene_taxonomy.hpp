#pragma once

#include <string>
#include <unordered_map>
#include <unordered_set>

namespace robot_life_cpp::common {

struct SceneTaxonomyRules {
  std::string default_scene{"generic_event"};
  std::unordered_map<std::string, std::string> event_scene_exact{};
  std::unordered_map<std::string, std::string> event_scene_token{
      {"face", "human_presence"},
      {"person_present", "human_presence"},
      {"audio", "speech_activity"},
      {"speech", "speech_activity"},
      {"gesture", "gesture_interaction"},
      {"hand", "gesture_interaction"},
      {"wave", "gesture_interaction"},
      {"motion", "motion_alert"},
      {"approaching", "motion_alert"},
      {"leaving", "motion_alert"},
      {"pose", "body_pose"},
  };
  std::unordered_set<std::string> proactive_scenes{
      "greeting_scene",
      "attention_scene",
      "gesture_bond_scene",
      "ambient_tracking_scene",
      "stranger_attention_scene",
  };
  std::unordered_set<std::string> safety_scenes{"safety_alert_scene"};
  std::unordered_set<std::string> attention_scenes{"attention_scene", "stranger_attention_scene"};
  std::unordered_set<std::string> engagement_scenes{"greeting_scene", "gesture_bond_scene"};
  std::unordered_set<std::string> noticed_scenes{
      "ambient_tracking_scene",
      "attention_scene",
      "stranger_attention_scene",
  };
  std::unordered_set<std::string> notice_events{
      "familiar_face_detected",
      "stranger_face_detected",
      "motion_detected",
  };
  std::unordered_set<std::string> mutual_events{
      "gaze_hold_start_detected",
      "gaze_sustained_detected",
  };
  std::unordered_set<std::string> engagement_events{
      "wave_detected",
      "gesture_detected",
  };
  std::unordered_set<std::string> social_behaviors{
      "perform_greeting",
      "greeting_visual_only",
      "perform_attention",
      "attention_minimal",
      "perform_gesture_response",
      "gesture_visual_only",
  };
};

}  // namespace robot_life_cpp::common
