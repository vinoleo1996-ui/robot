#include "robot_life_cpp/behavior/behavior_registry.hpp"

#include "robot_life_cpp/common/contracts.hpp"

namespace robot_life_cpp::behavior {

BehaviorRegistry::BehaviorRegistry() {
  using namespace common::contracts;
  templates_.emplace(
      std::string(BEHAVIOR_PERFORM_GREETING),
      BehaviorTemplate{
          std::string(BEHAVIOR_PERFORM_GREETING),
          {"guard_scene_validity", "state_greet", "act_nonverbal", "act_speech_optional", "state_recover", "release"},
          true,
          true,
      });
  templates_.emplace(
      std::string(BEHAVIOR_GREETING_VISUAL_ONLY),
      BehaviorTemplate{
          std::string(BEHAVIOR_GREETING_VISUAL_ONLY),
          {"guard_scene_validity", "state_greet", "act_nonverbal", "state_recover", "release"},
          true,
          false,
      });
  templates_.emplace(
      std::string(BEHAVIOR_PERFORM_ATTENTION),
      BehaviorTemplate{
          std::string(BEHAVIOR_PERFORM_ATTENTION),
          {"guard_scene_validity", "state_attention", "state_observe", "act_nonverbal", "state_recover", "release"},
          true,
          false,
      });
  templates_.emplace(
      std::string(BEHAVIOR_ATTENTION_MINIMAL),
      BehaviorTemplate{
          std::string(BEHAVIOR_ATTENTION_MINIMAL),
          {"state_attention", "act_nonverbal", "state_recover", "release"},
          true,
          false,
      });
  templates_.emplace(
      std::string(BEHAVIOR_PERFORM_GESTURE_RESPONSE),
      BehaviorTemplate{
          std::string(BEHAVIOR_PERFORM_GESTURE_RESPONSE),
          {"guard_scene_validity", "state_greet", "state_observe", "act_nonverbal", "act_speech_optional", "state_recover", "release"},
          true,
          true,
      });
  templates_.emplace(
      std::string(BEHAVIOR_GESTURE_VISUAL_ONLY),
      BehaviorTemplate{
          std::string(BEHAVIOR_GESTURE_VISUAL_ONLY),
          {"guard_scene_validity", "state_greet", "act_nonverbal", "state_recover", "release"},
          true,
          false,
      });
  templates_.emplace(
      std::string(BEHAVIOR_PERFORM_SAFETY_ALERT),
      BehaviorTemplate{
          std::string(BEHAVIOR_PERFORM_SAFETY_ALERT),
          {"guard_scene_validity", "state_alert", "act_nonverbal", "act_speech_optional", "state_recover", "release"},
          false,
          true,
      });
  templates_.emplace(
      std::string(BEHAVIOR_PERFORM_TRACKING),
      BehaviorTemplate{
          std::string(BEHAVIOR_PERFORM_TRACKING),
          {"state_observe", "act_nonverbal", "monitor_preemption", "state_idle", "release"},
          true,
          false,
      });
}

BehaviorTemplate BehaviorRegistry::get(const std::string& behavior_id) const {
  const auto it = templates_.find(behavior_id);
  if (it != templates_.end()) {
    return it->second;
  }
  return BehaviorTemplate{
      behavior_id,
      {"state_observe", "act_nonverbal", "state_idle", "release"},
      true,
      false,
  };
}

}  // namespace robot_life_cpp::behavior
