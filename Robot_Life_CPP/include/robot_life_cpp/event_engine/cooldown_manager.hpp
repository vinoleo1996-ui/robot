#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/scene_taxonomy.hpp"
#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct CooldownCheckInput {
  std::string scene_type{};
  std::optional<std::string> target_id{};
  common::EventPriority priority{common::EventPriority::P2};
  std::optional<std::string> active_target_id{};
  std::optional<std::string> active_behavior_id{};
  bool robot_busy{false};
};

struct CooldownCheckResult {
  bool allowed{true};
  std::string reason{"ok"};
};

struct CooldownSnapshot {
  double global_remaining_s{0.0};
  std::unordered_map<std::string, double> scene_remaining{};
  std::size_t tracked_scenes{0};
  double saturation_window_s{20.0};
  int saturation_limit{3};
  std::size_t recent_proactive_executions{0};
};

class CooldownManager {
 public:
  explicit CooldownManager(
      double global_cooldown_s = 3.0,
      std::unordered_map<std::string, double> scene_cooldowns = {},
      double saturation_window_s = 20.0,
      int saturation_limit = 3,
      common::SceneTaxonomyRules taxonomy = {});

  CooldownCheckResult check(const CooldownCheckInput& input, double now_mono_s = common::now_mono());
  void record_execution(
      const std::string& scene_type,
      std::optional<std::string> target_id = std::nullopt,
      double now_mono_s = common::now_mono());

  void reset();
  CooldownSnapshot snapshot(double now_mono_s = common::now_mono());

 private:
  bool is_proactive_scene(const std::string& scene_type) const;
  bool should_suppress_for_active_target(const CooldownCheckInput& input) const;
  bool is_saturated(const std::string& scene_type, common::EventPriority priority, double now_mono_s);
  void gc_stale(double now_mono_s);
  void gc_proactive_history(double now_mono_s);
  static std::string scene_target_key(const std::string& scene_type, const std::optional<std::string>& target_id);

  double global_cooldown_s_{3.0};
  std::unordered_map<std::string, double> scene_cooldowns_{};
  double saturation_window_s_{20.0};
  int saturation_limit_{3};
  common::SceneTaxonomyRules taxonomy_{};

  double last_execution_at_{0.0};
  std::unordered_map<std::string, double> scene_last_at_{};
  std::vector<std::tuple<double, std::string, std::string>> proactive_history_{};

  double gc_last_at_{0.0};
  double gc_interval_s_{30.0};
};

}  // namespace robot_life_cpp::event_engine
