#pragma once

#include <optional>
#include <string>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

struct SceneCoordinatorRules {
  double scene_ttl_s{2.0};
  double min_confidence{0.0};
};

class SceneCoordinator {
 public:
  explicit SceneCoordinator(SceneCoordinatorRules rules = {});

  void reconfigure(SceneCoordinatorRules rules);
  std::vector<common::SceneCandidate> derive(
      const std::vector<common::StableEvent>& stable_events,
      double now_mono_s = common::now_mono()) const;

 private:
  static std::optional<std::string> map_event_to_scene(
      const std::string& event_type,
      const common::Payload& payload);
  static std::optional<std::string> map_scene_to_behavior(const std::string& scene_type);
  static std::optional<std::string> resolve_target_id(const common::StableEvent& event);
  static double confidence_of(const common::StableEvent& event);

  SceneCoordinatorRules rules_{};
};

}  // namespace robot_life_cpp::runtime
