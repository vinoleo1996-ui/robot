#include "robot_life_cpp/runtime/execution_manager.hpp"

namespace robot_life_cpp::runtime {

ExecutionManager::ExecutionManager(behavior::BehaviorExecutor executor)
    : executor_(std::move(executor)) {}

common::ExecutionResult ExecutionManager::dispatch_decision(
    const common::ArbitrationResult& decision,
    int duration_ms,
    double now_mono_s) {
  auto execution = executor_.execute(decision, duration_ms, now_mono_s);
  history_.push_back(execution);
  return execution;
}

std::optional<common::ExecutionResult> ExecutionManager::interrupt_active(
    common::DecisionMode mode,
    double now_mono_s) {
  auto interrupted = executor_.interrupt_current(mode, now_mono_s);
  if (interrupted.has_value()) {
    history_.push_back(*interrupted);
  }
  return interrupted;
}

std::vector<common::ArbitrationResult> ExecutionManager::drain_resume_decisions() {
  std::vector<common::ArbitrationResult> drained{};
  while (true) {
    auto resumed = executor_.pop_resume_decision();
    if (!resumed.has_value()) {
      break;
    }
    drained.push_back(*resumed);
  }
  return drained;
}

std::optional<common::ExecutionResult> ExecutionManager::current_execution() const {
  return executor_.current_execution();
}

const std::vector<common::ExecutionResult>& ExecutionManager::history() const { return history_; }

std::unordered_map<std::string, std::string> ExecutionManager::resource_status(double now_mono_s) {
  return executor_.get_resource_status(now_mono_s);
}

}  // namespace robot_life_cpp::runtime
