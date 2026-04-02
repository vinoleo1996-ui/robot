#include "robot_life_cpp/behavior/executor.hpp"

#include <algorithm>

namespace robot_life_cpp::behavior {

BehaviorExecutor::BehaviorExecutor()
    : BehaviorExecutor(ResourceManager{}, BehaviorSafetyGuard{}) {}

BehaviorExecutor::BehaviorExecutor(
    ResourceManager resource_manager,
    BehaviorSafetyGuard safety_guard)
    : resource_manager_(std::move(resource_manager)),
      safety_guard_(std::move(safety_guard)) {}

common::ExecutionResult BehaviorExecutor::execute(
    const common::ArbitrationResult& decision,
    int duration_ms,
    double now_mono_s) {
  const auto started_at = now_mono_s;
  const auto safety = safety_guard_.evaluate(decision, last_decision_);

  if (safety.estop_required) {
    interrupt_current(common::DecisionMode::HardInterrupt, now_mono_s);
    pending_resume_decisions_.clear();
    resource_manager_.force_release_all();
  }

  if (!safety.allowed) {
    common::ExecutionResult blocked{};
    blocked.execution_id = common::new_id();
    blocked.trace_id = decision.trace_id;
    blocked.behavior_id = decision.target_behavior;
    blocked.status = "blocked";
    blocked.started_at = started_at;
    blocked.ended_at = now_mono_s;
    return blocked;
  }

  std::optional<common::ArbitrationResult> resume_candidate{};
  if (decision.mode == common::DecisionMode::SoftInterrupt ||
      decision.mode == common::DecisionMode::HardInterrupt) {
    if (active_execution_.has_value() && last_decision_.has_value() && last_decision_->resume_previous) {
      resume_candidate = *last_decision_;
    }
    auto interrupted = interrupt_current(decision.mode, now_mono_s);
    if (decision.mode == common::DecisionMode::HardInterrupt && !decision.resume_previous) {
      pending_resume_decisions_.clear();
    }
    (void)interrupted;
  }

  auto grant = resource_manager_.request_grant(
      decision.trace_id,
      decision.decision_id,
      decision.target_behavior,
      decision.required_resources,
      decision.optional_resources,
      priority_to_internal(decision.priority),
      duration_ms,
      now_mono_s);

  const bool can_fallback_to_degraded =
      decision.degraded_behavior.has_value() &&
      grant.granted_resources.size() >= decision.required_resources.size();

  if (!grant.granted && !decision.required_resources.empty() && !can_fallback_to_degraded) {
    common::ExecutionResult failed{};
    failed.execution_id = common::new_id();
    failed.trace_id = decision.trace_id;
    failed.behavior_id = decision.target_behavior;
    failed.status = "failed";
    failed.started_at = started_at;
    failed.ended_at = now_mono_s;
    return failed;
  }

  common::ExecutionResult execution{};
  execution.execution_id = common::new_id();
  execution.trace_id = decision.trace_id;
  execution.behavior_id = decision.target_behavior;
  execution.started_at = started_at;
  execution.ended_at = now_mono_s + 0.001;
  execution.interrupted = false;

  const bool use_degraded =
      (!grant.granted || decision.mode == common::DecisionMode::DegradeAndExecute) &&
      decision.degraded_behavior.has_value();
  if (use_degraded) {
    execution.behavior_id = *decision.degraded_behavior;
    execution.degraded = true;
    execution.status = "degraded";
  } else {
    execution.degraded = false;
    execution.status = "finished";
  }

  active_grant_id_ = grant.grant_id;
  active_execution_ = execution;
  last_decision_ = decision;

  if (resume_candidate.has_value()) {
    common::ArbitrationResult resumed{};
    resumed.decision_id = common::new_id();
    resumed.trace_id = resume_candidate->trace_id;
    resumed.target_behavior = resume_candidate->target_behavior;
    resumed.priority = resume_candidate->priority;
    resumed.mode = common::DecisionMode::Execute;
    resumed.required_resources = resume_candidate->required_resources;
    resumed.optional_resources = resume_candidate->optional_resources;
    resumed.degraded_behavior = resume_candidate->degraded_behavior;
    resumed.resume_previous = false;
    resumed.reason = "resume_after_interrupt:" + decision.target_behavior;
    pending_resume_decisions_.push_back(std::move(resumed));
  }

  if (active_grant_id_.has_value()) {
    resource_manager_.release_grant(*active_grant_id_);
    active_grant_id_.reset();
  }
  active_execution_.reset();
  return execution;
}

std::optional<common::ExecutionResult> BehaviorExecutor::interrupt_current(
    common::DecisionMode mode,
    double now_mono_s) {
  if (!active_execution_.has_value()) {
    return std::nullopt;
  }
  auto interrupted = *active_execution_;
  interrupted.status = "interrupted";
  interrupted.interrupted = true;
  interrupted.ended_at = now_mono_s;
  active_execution_.reset();
  if (active_grant_id_.has_value()) {
    resource_manager_.release_grant(*active_grant_id_);
    active_grant_id_.reset();
  }
  (void)mode;
  return interrupted;
}

std::optional<common::ArbitrationResult> BehaviorExecutor::pop_resume_decision() {
  if (pending_resume_decisions_.empty()) {
    return std::nullopt;
  }
  auto resumed = pending_resume_decisions_.front();
  pending_resume_decisions_.erase(pending_resume_decisions_.begin());
  return resumed;
}

std::optional<common::ExecutionResult> BehaviorExecutor::current_execution() const {
  return active_execution_;
}

std::unordered_map<std::string, std::string> BehaviorExecutor::get_resource_status(
    double now_mono_s) {
  return resource_manager_.get_resource_status(now_mono_s);
}

int BehaviorExecutor::priority_to_internal(common::EventPriority priority) {
  const auto rank = common::priority_rank(priority);
  return std::clamp(3 - rank, 0, 3);
}

std::string BehaviorExecutor::behavior_to_scene(const std::string& behavior_id) {
  if (behavior_id == "perform_safety_alert") {
    return "safety_alert_scene";
  }
  if (behavior_id == "perform_gesture_response" || behavior_id == "gesture_visual_only") {
    return "gesture_bond_scene";
  }
  if (behavior_id == "perform_greeting" || behavior_id == "greeting_visual_only") {
    return "greeting_scene";
  }
  if (behavior_id == "perform_attention" || behavior_id == "attention_minimal") {
    return "attention_scene";
  }
  if (behavior_id == "perform_tracking") {
    return "ambient_tracking_scene";
  }
  return "generic_event";
}

}  // namespace robot_life_cpp::behavior
