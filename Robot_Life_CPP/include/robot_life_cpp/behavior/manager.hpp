#pragma once

#include <optional>
#include <string>
#include <vector>

#include "robot_life_cpp/event_engine/policy_layer.hpp"

namespace robot_life_cpp::behavior {

struct BehaviorPlan {
  std::string target_behavior;
  std::optional<std::string> degraded_behavior;
  std::vector<std::string> required_resources{};
  std::vector<std::string> optional_resources{};
  bool resume_previous{true};
  std::string reason;
};

struct BehaviorRule {
  std::string target_behavior;
  std::optional<std::string> degraded_behavior;
  std::vector<std::string> required_resources{};
  std::vector<std::string> optional_resources{};
  bool resume_previous{true};
};

class BehaviorManager {
 public:
  BehaviorPlan plan(
      const std::string& scene_type,
      const BehaviorRule& rule,
      const event_engine::PolicyDecision& policy) const;
};

}  // namespace robot_life_cpp::behavior
