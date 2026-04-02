#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct ArbitratorRules {
  double decision_cooldown_s{0.6};
  std::unordered_map<std::string, common::EventPriority> scene_priority{
      {"gesture_interaction", common::EventPriority::P0},
      {"speech_activity", common::EventPriority::P1},
      {"human_presence", common::EventPriority::P1},
      {"motion_alert", common::EventPriority::P2},
      {"body_pose", common::EventPriority::P2},
      {"generic_event", common::EventPriority::P3},
  };
  std::unordered_map<std::string, std::string> behavior_by_scene{
      {"gesture_interaction", "interactive_gesture"},
      {"speech_activity", "voice_response"},
      {"human_presence", "engage_presence"},
      {"motion_alert", "motion_observe"},
      {"body_pose", "posture_react"},
      {"generic_event", "idle_scan"},
  };
};

class Arbitrator {
 public:
  explicit Arbitrator(ArbitratorRules rules = {});

  std::optional<common::ArbitrationResult> decide(
      const std::vector<common::SceneCandidate>& scenes,
      double now_mono_s = common::now_mono());

  void reset();

 private:
  bool is_scene_cooled_down(const std::string& scene_type, double now_mono_s) const;
  common::EventPriority scene_priority(const std::string& scene_type) const;
  std::string behavior_for_scene(const std::string& scene_type) const;

  ArbitratorRules rules_;
  std::unordered_map<std::string, double> scene_last_decision_time_{};
};

}  // namespace robot_life_cpp::event_engine
