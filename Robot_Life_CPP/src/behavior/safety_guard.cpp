#include "robot_life_cpp/behavior/safety_guard.hpp"

#include <algorithm>
#include <cctype>

namespace robot_life_cpp::behavior {

namespace {
std::string normalize(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}
}  // namespace

BehaviorSafetyGuard::BehaviorSafetyGuard(bool enabled) : enabled_(enabled) {
  dangerous_behavior_allowlist_ = {
      "perform_greeting",
      "perform_attention",
      "perform_gesture_response",
      "perform_tracking",
      "perform_safety_alert",
      "greeting_visual_only",
      "attention_minimal",
      "gesture_visual_only",
  };

  dangerous_behavior_tokens_ = {"swing", "strike", "throw", "kick", "slam", "dash"};
  emergency_behavior_tokens_ = {"safety_alert", "emergency_stop", "estop", "e_stop", "panic"};
  emergency_reason_tokens_ = {"emergency", "collision", "safety", "danger", "estop", "panic"};

  behavior_mutex_ = {
      {"perform_safety_alert", {"perform_greeting", "perform_attention", "perform_gesture_response", "perform_tracking"}},
      {"perform_greeting", {"perform_attention", "perform_gesture_response", "perform_tracking"}},
      {"perform_attention", {"perform_greeting", "perform_gesture_response", "perform_tracking"}},
      {"perform_gesture_response", {"perform_greeting", "perform_attention", "perform_tracking"}},
      {"perform_tracking", {"perform_greeting", "perform_attention", "perform_gesture_response"}},
  };
  for (const auto& [behavior, conflicts] : behavior_mutex_) {
    for (const auto& target : conflicts) {
      behavior_mutex_[target].insert(behavior);
    }
  }
}

SafetyGuardOutcome BehaviorSafetyGuard::evaluate(
    const common::ArbitrationResult& decision,
    const std::optional<common::ArbitrationResult>& current_decision) const {
  if (!enabled_) {
    return {.allowed = true, .reason = "disabled", .estop_required = false};
  }

  if (is_emergency_decision(decision)) {
    return {.allowed = true, .reason = "emergency_stop_preempt", .estop_required = true};
  }

  const auto normalized_behavior = normalize(decision.target_behavior);
  if (is_dangerous_behavior(normalized_behavior) &&
      !dangerous_behavior_allowlist_.contains(decision.target_behavior)) {
    return {
        .allowed = false,
        .reason = "dangerous_behavior_not_allowlisted:" + decision.target_behavior,
        .estop_required = false,
    };
  }

  if (current_decision.has_value() &&
      is_mutex_conflict(current_decision->target_behavior, decision.target_behavior)) {
    if (common::priority_rank(decision.priority) >= common::priority_rank(current_decision->priority)) {
      if (decision.mode != common::DecisionMode::SoftInterrupt &&
          decision.mode != common::DecisionMode::HardInterrupt) {
        return {
            .allowed = false,
            .reason = "mutex_conflict_requires_interrupt:" + current_decision->target_behavior +
                      "->" + decision.target_behavior,
            .estop_required = false,
        };
      }
    }
  }

  return {.allowed = true, .reason = "ok", .estop_required = false};
}

bool BehaviorSafetyGuard::is_dangerous_behavior(const std::string& normalized_behavior) const {
  for (const auto& token : dangerous_behavior_tokens_) {
    if (normalized_behavior.find(token) != std::string::npos) {
      return true;
    }
  }
  return false;
}

bool BehaviorSafetyGuard::is_emergency_decision(const common::ArbitrationResult& decision) const {
  if (decision.priority == common::EventPriority::P0) {
    return true;
  }

  const auto behavior = normalize(decision.target_behavior);
  const auto reason = normalize(decision.reason);

  for (const auto& token : emergency_behavior_tokens_) {
    if (behavior.find(token) != std::string::npos) {
      return true;
    }
  }
  for (const auto& token : emergency_reason_tokens_) {
    if (reason.find(token) != std::string::npos) {
      return true;
    }
  }
  return false;
}

bool BehaviorSafetyGuard::is_mutex_conflict(
    const std::string& current,
    const std::string& incoming) const {
  auto current_it = behavior_mutex_.find(current);
  if (current_it != behavior_mutex_.end() && current_it->second.contains(incoming)) {
    return true;
  }
  auto incoming_it = behavior_mutex_.find(incoming);
  if (incoming_it != behavior_mutex_.end() && incoming_it->second.contains(current)) {
    return true;
  }
  return false;
}

}  // namespace robot_life_cpp::behavior
