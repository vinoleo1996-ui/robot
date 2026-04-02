#pragma once

#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/scene_taxonomy.hpp"
#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct SceneAggregatorRules {
  double scene_ttl_s{2.0};
  double score_decay_s{1.2};
  common::SceneTaxonomyRules taxonomy{};
  std::unordered_map<std::string, double> scene_bias{
      {"human_presence", 1.1},
      {"speech_activity", 1.0},
      {"gesture_interaction", 1.2},
      {"motion_alert", 0.9},
      {"body_pose", 0.95},
  };
};

class SceneAggregator {
 public:
  explicit SceneAggregator(SceneAggregatorRules rules = {});

  std::vector<common::SceneCandidate> update(
      const std::vector<common::StableEvent>& stable_events,
      double now_mono_s = common::now_mono());

  void reset();

 private:
  struct SceneState {
    double score{0.0};
    double last_update{0.0};
    std::vector<std::string> event_ids{};
    std::string trace_id{};
  };

  std::string classify_scene(const std::string& event_type) const;
  static double event_score_hint(const common::StableEvent& event);
  void gc(double now_mono_s);

  SceneAggregatorRules rules_;
  std::unordered_map<std::string, SceneState> states_;
  std::uint64_t gc_calls_{0};
};

}  // namespace robot_life_cpp::event_engine
