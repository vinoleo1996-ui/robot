#include "robot_life_cpp/runtime/interaction_intent.hpp"

#include "robot_life_cpp/common/interaction_intent.hpp"

namespace robot_life_cpp::runtime {

std::string intent_for_state(const std::optional<std::string>& state_name) {
  return common::intent_for_state(state_name);
}

std::string intent_from_snapshot(
    const std::unordered_map<std::string, std::string>& snapshot) {
  return common::intent_from_snapshot(snapshot);
}

}  // namespace robot_life_cpp::runtime
