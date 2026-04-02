#include "robot_life_cpp/runtime/life_state.hpp"

#include <algorithm>
#include <set>

namespace robot_life_cpp::runtime {

namespace {

std::optional<std::string> latest_target_id_from_events(
    const std::vector<common::StableEvent>& events,
    const std::unordered_set<std::string>& preferred_event_types) {
  for (auto it = events.rbegin(); it != events.rend(); ++it) {
    if (!preferred_event_types.contains(it->event_type)) {
      continue;
    }
    auto target_it = it->payload.find("target_id");
    if (target_it != it->payload.end() && !target_it->second.empty()) {
      return target_it->second;
    }
  }
  return std::nullopt;
}

std::optional<double> parse_optional_double(const common::Payload& payload, const std::string& key) {
  const auto it = payload.find(key);
  if (it == payload.end() || it->second.empty()) {
    return std::nullopt;
  }
  try {
    return std::stod(it->second);
  } catch (...) {
    return std::nullopt;
  }
}

}  // namespace

LifeStateSnapshot build_life_state_snapshot(
    const std::vector<common::StableEvent>& stable_events,
    const std::vector<common::SceneCandidate>& scene_candidates,
    const std::vector<common::ExecutionResult>& execution_results,
    const common::SceneTaxonomyRules& taxonomy) {
  LifeStateSnapshot snapshot{};

  if (!scene_candidates.empty()) {
    snapshot.latest_scene = scene_candidates.back();
    snapshot.latest_scene_payload = scene_candidates.back().payload;
    auto state_it = snapshot.latest_scene_payload.find("interaction_state");
    if (state_it != snapshot.latest_scene_payload.end()) {
      snapshot.latest_interaction_state = state_it->second;
    }
    auto path_it = snapshot.latest_scene_payload.find("scene_path");
    if (path_it != snapshot.latest_scene_payload.end()) {
      snapshot.latest_scene_path = path_it->second;
    }
    snapshot.latest_target_id = scene_candidates.back().target_id;
    snapshot.latest_engagement_score = parse_optional_double(snapshot.latest_scene_payload, "engagement_score");
  }

  std::set<std::string> event_set{};
  snapshot.has_p0_event = false;
  for (const auto& event : stable_events) {
    event_set.insert(event.event_type);
    if (event.priority == common::EventPriority::P0) {
      snapshot.has_p0_event = true;
    }
  }
  snapshot.stable_event_types.assign(event_set.begin(), event_set.end());

  for (const auto& execution : execution_results) {
    if (taxonomy.social_behaviors.contains(execution.behavior_id)) {
      snapshot.social_execution = execution;
      break;
    }
  }

  snapshot.noticed_target_id = latest_target_id_from_events(stable_events, taxonomy.notice_events);
  if (!snapshot.noticed_target_id.has_value()) {
    snapshot.noticed_target_id = snapshot.latest_target_id;
  }

  snapshot.mutual_target_id = latest_target_id_from_events(stable_events, taxonomy.mutual_events);
  if (!snapshot.mutual_target_id.has_value()) {
    snapshot.mutual_target_id = snapshot.latest_target_id;
  }

  snapshot.engagement_target_id = latest_target_id_from_events(stable_events, taxonomy.engagement_events);
  if (!snapshot.engagement_target_id.has_value()) {
    snapshot.engagement_target_id = snapshot.latest_target_id;
  }

  snapshot.has_safety_scene = std::any_of(
      scene_candidates.begin(),
      scene_candidates.end(),
      [&](const common::SceneCandidate& scene) { return taxonomy.safety_scenes.contains(scene.scene_type); });

  const bool has_attention_lost_event =
      event_set.contains("attention_lost_detected") || event_set.contains("gaze_hold_end_detected");
  snapshot.has_attention_lost = has_attention_lost_event;

  snapshot.has_engagement_scene =
      std::any_of(
          scene_candidates.begin(),
          scene_candidates.end(),
          [&](const common::SceneCandidate& scene) { return taxonomy.engagement_scenes.contains(scene.scene_type); }) ||
      event_set.contains("wave_detected");

  const bool has_attention_scene = std::any_of(
      scene_candidates.begin(),
      scene_candidates.end(),
      [&](const common::SceneCandidate& scene) { return taxonomy.attention_scenes.contains(scene.scene_type); });
  snapshot.has_mutual_attention_signal =
      snapshot.latest_interaction_state == "engaging" ||
      snapshot.latest_interaction_state == "mutual_attention" ||
      has_attention_scene ||
      event_set.contains("gaze_hold_start_detected") ||
      event_set.contains("gaze_sustained_detected");

  const bool has_noticed_scene = std::any_of(
      scene_candidates.begin(),
      scene_candidates.end(),
      [&](const common::SceneCandidate& scene) { return taxonomy.noticed_scenes.contains(scene.scene_type); });
  snapshot.has_notice_signal =
      has_noticed_scene ||
      event_set.contains("familiar_face_detected") ||
      event_set.contains("stranger_face_detected") ||
      event_set.contains("motion_detected");

  return snapshot;
}

}  // namespace robot_life_cpp::runtime
