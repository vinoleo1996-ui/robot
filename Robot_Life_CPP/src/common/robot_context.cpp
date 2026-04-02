#include "robot_life_cpp/common/robot_context.hpp"

#include <algorithm>
#include <chrono>

namespace robot_life_cpp::common {

RobotContextStore::RobotContextStore(
    std::string mode,
    bool do_not_disturb,
    std::optional<double> battery_level,
    int max_recent_interactions)
    : mode_(std::move(mode)),
      do_not_disturb_(do_not_disturb),
      battery_level_(battery_level),
      updated_at_(now_mono()),
      max_recent_interactions_(static_cast<std::size_t>(std::max(1, max_recent_interactions))) {}

void RobotContextStore::set_mode(const std::string& mode) {
  mode_ = mode;
  updated_at_ = now_mono();
}

void RobotContextStore::set_do_not_disturb(bool enabled) {
  do_not_disturb_ = enabled;
  updated_at_ = now_mono();
}

void RobotContextStore::mark_active_behavior(
    const std::optional<std::string>& behavior_id,
    const std::optional<std::string>& status) {
  active_behavior_id_ = behavior_id;
  active_behavior_status_ = status;
  const auto active = behavior_id.value_or("");
  speaking_ = active.rfind("perform_greeting", 0) == 0 ||
              active.rfind("perform_safety_alert", 0) == 0;
  moving_ = active.rfind("perform_", 0) == 0;
  updated_at_ = now_mono();
}

void RobotContextStore::set_interaction_context(
    const std::optional<std::string>& target_id,
    const std::optional<std::string>& episode_id,
    const std::optional<std::string>& intent) {
  current_interaction_target_ = target_id;
  current_interaction_episode_id_ = episode_id;
  current_intent_ = intent;
  updated_at_ = now_mono();
}

void RobotContextStore::push_finished_interaction(const RecentInteraction& item) {
  if (recent_interactions_.size() >= max_recent_interactions_) {
    recent_interactions_.pop_front();
  }
  recent_interactions_.push_back(item);
  updated_at_ = now_mono();
}

std::unordered_map<std::string, std::string> RobotContextStore::snapshot() const {
  std::unordered_map<std::string, std::string> out{};
  out["mode"] = mode_;
  out["do_not_disturb"] = do_not_disturb_ ? "true" : "false";
  if (battery_level_.has_value()) {
    out["battery_level"] = std::to_string(*battery_level_);
  }
  out["speaking"] = speaking_ ? "true" : "false";
  out["listening"] = listening_ ? "true" : "false";
  out["moving"] = moving_ ? "true" : "false";
  if (active_behavior_id_.has_value()) {
    out["active_behavior_id"] = *active_behavior_id_;
  }
  if (active_behavior_status_.has_value()) {
    out["active_behavior_status"] = *active_behavior_status_;
  }
  if (current_interaction_target_.has_value()) {
    out["current_interaction_target"] = *current_interaction_target_;
  }
  if (current_interaction_episode_id_.has_value()) {
    out["current_interaction_episode_id"] = *current_interaction_episode_id_;
  }
  if (current_intent_.has_value()) {
    out["current_intent"] = *current_intent_;
  }
  out["recent_interactions_count"] = std::to_string(recent_interactions_.size());
  out["updated_at"] = std::to_string(updated_at_);
  return out;
}

double RobotContextStore::now_mono() {
  using clock = std::chrono::steady_clock;
  return std::chrono::duration<double>(clock::now().time_since_epoch()).count();
}

}  // namespace robot_life_cpp::common
