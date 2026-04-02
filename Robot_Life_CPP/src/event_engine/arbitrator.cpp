#include "robot_life_cpp/event_engine/arbitrator.hpp"

#include <algorithm>

namespace robot_life_cpp::event_engine {

Arbitrator::Arbitrator(ArbitratorRules rules) : rules_(std::move(rules)) {
  rules_.decision_cooldown_s = std::max(0.0, rules_.decision_cooldown_s);
}

std::optional<common::ArbitrationResult> Arbitrator::decide(
    const std::vector<common::SceneCandidate>& scenes, double now_mono_s) {
  if (scenes.empty()) {
    return std::nullopt;
  }

  const common::SceneCandidate* chosen = nullptr;
  common::EventPriority chosen_priority = common::EventPriority::P3;

  for (const auto& scene : scenes) {
    if (now_mono_s > scene.valid_until_monotonic) {
      continue;
    }
    if (is_scene_cooled_down(scene.scene_type, now_mono_s)) {
      continue;
    }
    const auto priority = scene_priority(scene.scene_type);
    if (chosen == nullptr || common::priority_rank(priority) < common::priority_rank(chosen_priority) ||
        (priority == chosen_priority && scene.score_hint > chosen->score_hint)) {
      chosen = &scene;
      chosen_priority = priority;
    }
  }

  if (chosen == nullptr) {
    return std::nullopt;
  }

  scene_last_decision_time_[chosen->scene_type] = now_mono_s;
  common::ArbitrationResult result{};
  result.decision_id = common::new_id();
  result.trace_id = chosen->trace_id;
  result.priority = chosen_priority;
  result.target_behavior = behavior_for_scene(chosen->scene_type);
  result.mode = chosen_priority == common::EventPriority::P0 ? common::DecisionMode::HardInterrupt
                                                              : common::DecisionMode::Execute;
  result.reason = "scene=" + chosen->scene_type + ", score=" + std::to_string(chosen->score_hint);
  result.required_resources = {"camera"};
  if (chosen->scene_type == "speech_activity") {
    result.required_resources.push_back("audio");
    result.optional_resources.push_back("gpu");
  }
  return result;
}

void Arbitrator::reset() { scene_last_decision_time_.clear(); }

bool Arbitrator::is_scene_cooled_down(const std::string& scene_type, double now_mono_s) const {
  if (rules_.decision_cooldown_s <= 0.0) {
    return false;
  }
  const auto it = scene_last_decision_time_.find(scene_type);
  if (it == scene_last_decision_time_.end()) {
    return false;
  }
  return (now_mono_s - it->second) < rules_.decision_cooldown_s;
}

common::EventPriority Arbitrator::scene_priority(const std::string& scene_type) const {
  const auto it = rules_.scene_priority.find(scene_type);
  return it == rules_.scene_priority.end() ? common::EventPriority::P2 : it->second;
}

std::string Arbitrator::behavior_for_scene(const std::string& scene_type) const {
  const auto it = rules_.behavior_by_scene.find(scene_type);
  return it == rules_.behavior_by_scene.end() ? "idle_scan" : it->second;
}

}  // namespace robot_life_cpp::event_engine
