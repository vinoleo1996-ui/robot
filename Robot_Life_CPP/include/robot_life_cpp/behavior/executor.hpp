#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/behavior/resources.hpp"
#include "robot_life_cpp/behavior/safety_guard.hpp"
#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::behavior {

class BehaviorExecutor {
 public:
  BehaviorExecutor();

  BehaviorExecutor(
      ResourceManager resource_manager,
      BehaviorSafetyGuard safety_guard);

  common::ExecutionResult execute(
      const common::ArbitrationResult& decision,
      int duration_ms = 5000,
      double now_mono_s = common::now_mono());

  std::optional<common::ExecutionResult> interrupt_current(
      common::DecisionMode mode = common::DecisionMode::SoftInterrupt,
      double now_mono_s = common::now_mono());

  std::optional<common::ArbitrationResult> pop_resume_decision();
  std::optional<common::ExecutionResult> current_execution() const;

  std::unordered_map<std::string, std::string> get_resource_status(
      double now_mono_s = common::now_mono());

 private:
  static int priority_to_internal(common::EventPriority priority);
  static std::string behavior_to_scene(const std::string& behavior_id);

  ResourceManager resource_manager_{};
  BehaviorSafetyGuard safety_guard_{};
  std::optional<common::ExecutionResult> active_execution_{};
  std::optional<common::ArbitrationResult> last_decision_{};
  std::optional<std::string> active_grant_id_{};
  std::vector<common::ArbitrationResult> pending_resume_decisions_{};
};

}  // namespace robot_life_cpp::behavior
