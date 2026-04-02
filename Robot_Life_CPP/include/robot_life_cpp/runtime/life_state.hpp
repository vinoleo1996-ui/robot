#pragma once

#include <optional>
#include <string>
#include <vector>

#include "robot_life_cpp/common/scene_taxonomy.hpp"
#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

struct LifeStateSnapshot {
  std::optional<common::SceneCandidate> latest_scene{};
  common::Payload latest_scene_payload{};
  std::string latest_interaction_state{};
  std::string latest_scene_path{};
  std::optional<std::string> latest_target_id{};
  std::optional<double> latest_engagement_score{};
  std::vector<std::string> stable_event_types{};
  std::optional<common::ExecutionResult> social_execution{};
  std::optional<std::string> noticed_target_id{};
  std::optional<std::string> mutual_target_id{};
  std::optional<std::string> engagement_target_id{};
  bool has_p0_event{false};
  bool has_safety_scene{false};
  bool has_attention_lost{false};
  bool has_engagement_scene{false};
  bool has_mutual_attention_signal{false};
  bool has_notice_signal{false};
};

LifeStateSnapshot build_life_state_snapshot(
    const std::vector<common::StableEvent>& stable_events,
    const std::vector<common::SceneCandidate>& scene_candidates,
    const std::vector<common::ExecutionResult>& execution_results,
    const common::SceneTaxonomyRules& taxonomy = {});

}  // namespace robot_life_cpp::runtime
