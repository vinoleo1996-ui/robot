#pragma once

#include <optional>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/behavior/executor.hpp"
#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

class ExecutionManager {
 public:
  explicit ExecutionManager(behavior::BehaviorExecutor executor = {});

  common::ExecutionResult dispatch_decision(
      const common::ArbitrationResult& decision,
      int duration_ms = 5000,
      double now_mono_s = common::now_mono());

  std::optional<common::ExecutionResult> interrupt_active(
      common::DecisionMode mode = common::DecisionMode::SoftInterrupt,
      double now_mono_s = common::now_mono());

  std::vector<common::ArbitrationResult> drain_resume_decisions();
  std::optional<common::ExecutionResult> current_execution() const;
  const std::vector<common::ExecutionResult>& history() const;

  std::unordered_map<std::string, std::string> resource_status(
      double now_mono_s = common::now_mono());

 private:
  behavior::BehaviorExecutor executor_{};
  std::vector<common::ExecutionResult> history_{};
};

}  // namespace robot_life_cpp::runtime

