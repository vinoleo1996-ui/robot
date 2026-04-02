#include "robot_life_cpp/behavior/manager.hpp"

namespace robot_life_cpp::behavior {

BehaviorPlan BehaviorManager::plan(
    const std::string& scene_type,
    const BehaviorRule& rule,
    const event_engine::PolicyDecision& policy) const {
  BehaviorPlan plan{};
  plan.target_behavior = rule.target_behavior;
  plan.degraded_behavior = rule.degraded_behavior;
  plan.required_resources = rule.required_resources;
  plan.optional_resources = rule.optional_resources;
  plan.resume_previous = rule.resume_previous;
  plan.reason = "behavior_plan:" + policy.response_level + ":" + scene_type;
  return plan;
}

}  // namespace robot_life_cpp::behavior
