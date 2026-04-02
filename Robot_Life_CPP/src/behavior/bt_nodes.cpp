#include "robot_life_cpp/behavior/bt_nodes.hpp"

#include <unordered_set>

namespace robot_life_cpp::behavior {

NodeResult run_node(const std::string& node_name, const std::string& behavior_id, bool degraded) {
  if (node_name == "state_idle") {
    return NodeResult{node_name, "success", "idle"};
  }
  if (node_name == "state_greet") {
    return NodeResult{node_name, "success", "greet"};
  }
  if (node_name == "state_attention") {
    return NodeResult{node_name, "success", "attention"};
  }
  if (node_name == "state_alert") {
    return NodeResult{node_name, "success", "alert"};
  }
  if (node_name == "state_observe") {
    return NodeResult{node_name, "success", "observe"};
  }
  if (node_name == "state_recover") {
    return NodeResult{node_name, "success", "recover"};
  }
  if (node_name == "guard_scene_validity") {
    return NodeResult{node_name, "success", ""};
  }
  if (node_name == "act_nonverbal") {
    return NodeResult{node_name, "success", degraded ? "degraded_nonverbal" : "full_nonverbal"};
  }
  if (node_name == "act_speech_optional") {
    return NodeResult{node_name, "success", degraded ? "speech_suppressed" : "speech_allowed"};
  }
  static const std::unordered_set<std::string> kSimpleSuccess{"monitor_preemption", "release"};
  if (kSimpleSuccess.contains(node_name)) {
    return NodeResult{node_name, "success", ""};
  }
  return NodeResult{node_name, "success", "unknown_node:" + behavior_id};
}

}  // namespace robot_life_cpp::behavior
