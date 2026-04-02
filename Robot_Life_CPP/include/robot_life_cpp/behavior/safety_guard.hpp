#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::behavior {

struct SafetyGuardOutcome {
  bool allowed{true};
  std::string reason{"ok"};
  bool estop_required{false};
};

class BehaviorSafetyGuard {
 public:
  explicit BehaviorSafetyGuard(bool enabled = true);

  SafetyGuardOutcome evaluate(
      const common::ArbitrationResult& decision,
      const std::optional<common::ArbitrationResult>& current_decision = std::nullopt) const;

 private:
  bool is_dangerous_behavior(const std::string& normalized_behavior) const;
  bool is_emergency_decision(const common::ArbitrationResult& decision) const;
  bool is_mutex_conflict(const std::string& current, const std::string& incoming) const;

  bool enabled_{true};
  std::unordered_set<std::string> dangerous_behavior_allowlist_{};
  std::unordered_set<std::string> dangerous_behavior_tokens_{};
  std::unordered_set<std::string> emergency_behavior_tokens_{};
  std::unordered_set<std::string> emergency_reason_tokens_{};
  std::unordered_map<std::string, std::unordered_set<std::string>> behavior_mutex_{};
};

}  // namespace robot_life_cpp::behavior

