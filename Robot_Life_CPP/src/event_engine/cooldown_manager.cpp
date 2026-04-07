#include "robot_life_cpp/event_engine/cooldown_manager.hpp"

#include <algorithm>
#include <cmath>
#include <tuple>

namespace robot_life_cpp::event_engine {

namespace {
std::unordered_map<std::string, double> default_scene_cooldowns() {
  return {
      {"greeting_scene", 1800.0},
      {"attention_scene", 300.0},
      {"gesture_bond_scene", 10.0},
      {"ambient_tracking_scene", 5.0},
      {"safety_alert_scene", 30.0},
  };
}
}  // namespace

CooldownManager::CooldownManager(
    double global_cooldown_s,
    std::unordered_map<std::string, double> scene_cooldowns,
    double saturation_window_s,
    int saturation_limit,
    common::SceneTaxonomyRules taxonomy)
    : global_cooldown_s_(std::max(0.0, global_cooldown_s)),
      scene_cooldowns_(scene_cooldowns.empty() ? default_scene_cooldowns() : std::move(scene_cooldowns)),
      saturation_window_s_(std::max(1.0, saturation_window_s)),
      saturation_limit_(std::max(1, saturation_limit)),
      taxonomy_(std::move(taxonomy)) {}

CooldownCheckResult CooldownManager::check(const CooldownCheckInput& input, double now_mono_s) {
  gc_stale(now_mono_s);

  if (input.priority == common::EventPriority::P0) {
    return {.allowed = true, .reason = "ok"};
  }

  if (should_suppress_for_active_target(input)) {
    const auto key = input.active_target_id.value_or("__any__");
    return {.allowed = false, .reason = "context_suppression:active_target:" + key};
  }

  if (input.robot_busy &&
      (input.priority == common::EventPriority::P2 || input.priority == common::EventPriority::P3)) {
    return {
        .allowed = false,
        .reason = "context_suppression:robot_busy:" + input.active_behavior_id.value_or("busy"),
    };
  }

  if (is_saturated(input.scene_type, input.priority, now_mono_s)) {
    return {
        .allowed = false,
        .reason = "saturation:" + std::to_string(saturation_limit_) + "_within_" +
                  std::to_string(static_cast<int>(std::round(saturation_window_s_))) + "s",
    };
  }

  if (input.priority != common::EventPriority::P0 && input.priority != common::EventPriority::P1 &&
      last_execution_at_ > 0.0) {
    const auto elapsed = now_mono_s - last_execution_at_;
    if (elapsed < global_cooldown_s_) {
      const auto remain_ms = static_cast<int>((global_cooldown_s_ - elapsed) * 1000.0);
      return {
          .allowed = false,
          .reason = "global_cooldown:" + std::to_string(std::max(0, remain_ms)) + "ms_remaining",
      };
    }
  }

  const auto cooldown_it = scene_cooldowns_.find(input.scene_type);
  const auto scene_cd = cooldown_it == scene_cooldowns_.end() ? 0.0 : cooldown_it->second;
  if (scene_cd > 0.0 && input.priority != common::EventPriority::P1) {
    const auto key = scene_target_key(input.scene_type, input.target_id);
    const auto last_it = scene_last_at_.find(key);
    if (last_it != scene_last_at_.end()) {
      const auto elapsed = now_mono_s - last_it->second;
      if (elapsed < scene_cd) {
        const auto remain_ms = static_cast<int>((scene_cd - elapsed) * 1000.0);
        return {
            .allowed = false,
            .reason = "scene_cooldown:" + input.scene_type + ":" + std::to_string(std::max(0, remain_ms)) +
                      "ms_remaining",
        };
      }
    }
  }

  return {.allowed = true, .reason = "ok"};
}

void CooldownManager::record_execution(
    const std::string& scene_type,
    std::optional<std::string> target_id,
    double now_mono_s) {
  last_execution_at_ = now_mono_s;
  scene_last_at_[scene_target_key(scene_type, target_id)] = now_mono_s;
  if (is_proactive_scene(scene_type)) {
    proactive_history_.push_back(std::make_tuple(now_mono_s, scene_type, target_id.value_or("__any__")));
    gc_proactive_history(now_mono_s);
  }
}

void CooldownManager::reset() {
  last_execution_at_ = 0.0;
  scene_last_at_.clear();
  proactive_history_.clear();
}

CooldownSnapshot CooldownManager::snapshot(double now_mono_s) {
  gc_proactive_history(now_mono_s);
  CooldownSnapshot snap{};
  if (last_execution_at_ > 0.0) {
    snap.global_remaining_s = std::max(0.0, global_cooldown_s_ - (now_mono_s - last_execution_at_));
  }
  for (const auto& [key, last_at] : scene_last_at_) {
    auto sep = key.find(':');
    const auto scene_type = sep == std::string::npos ? key : key.substr(0, sep);
    const auto cooldown_it = scene_cooldowns_.find(scene_type);
    if (cooldown_it == scene_cooldowns_.end()) {
      continue;
    }
    const auto remaining = std::max(0.0, cooldown_it->second - (now_mono_s - last_at));
    if (remaining > 0.0) {
      snap.scene_remaining[key] = remaining;
    }
  }
  snap.tracked_scenes = scene_last_at_.size();
  snap.saturation_window_s = saturation_window_s_;
  snap.saturation_limit = saturation_limit_;
  snap.recent_proactive_executions = proactive_history_.size();
  return snap;
}

bool CooldownManager::is_proactive_scene(const std::string& scene_type) const {
  return taxonomy_.proactive_scenes.contains(scene_type);
}

bool CooldownManager::should_suppress_for_active_target(const CooldownCheckInput& input) const {
  if (input.priority == common::EventPriority::P0 || input.priority == common::EventPriority::P1) {
    return false;
  }
  if (!is_proactive_scene(input.scene_type)) {
    return false;
  }
  if (!input.active_target_id.has_value() || !input.target_id.has_value()) {
    return false;
  }
  return *input.active_target_id != *input.target_id;
}

bool CooldownManager::is_saturated(
    const std::string& scene_type,
    common::EventPriority priority,
    double now_mono_s) {
  if (priority == common::EventPriority::P0 || priority == common::EventPriority::P1) {
    return false;
  }
  if (!is_proactive_scene(scene_type)) {
    return false;
  }
  gc_proactive_history(now_mono_s);
  return static_cast<int>(proactive_history_.size()) >= saturation_limit_;
}

void CooldownManager::gc_stale(double now_mono_s) {
  const auto elapsed = gc_last_at_ <= 0.0 ? 1e9 : (now_mono_s - gc_last_at_);
  if (elapsed < gc_interval_s_) {
    return;
  }
  gc_last_at_ = now_mono_s;

  std::vector<std::string> stale{};
  stale.reserve(scene_last_at_.size());
  for (const auto& [key, last_at] : scene_last_at_) {
    auto sep = key.find(':');
    const auto scene_type = sep == std::string::npos ? key : key.substr(0, sep);
    const auto cooldown_it = scene_cooldowns_.find(scene_type);
    const auto scene_cd = cooldown_it == scene_cooldowns_.end() ? 60.0 : cooldown_it->second;
    if ((now_mono_s - last_at) > (scene_cd * 2.0)) {
      stale.push_back(key);
    }
  }
  for (const auto& key : stale) {
    scene_last_at_.erase(key);
  }
  gc_proactive_history(now_mono_s);
}

void CooldownManager::gc_proactive_history(double now_mono_s) {
  proactive_history_.erase(
      std::remove_if(
          proactive_history_.begin(),
          proactive_history_.end(),
          [&](const auto& item) { return (now_mono_s - std::get<0>(item)) > saturation_window_s_; }),
      proactive_history_.end());
}

std::string CooldownManager::scene_target_key(
    const std::string& scene_type,
    const std::optional<std::string>& target_id) {
  return scene_type + ":" + target_id.value_or("__any__");
}

}  // namespace robot_life_cpp::event_engine
