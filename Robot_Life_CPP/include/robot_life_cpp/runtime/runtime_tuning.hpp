#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <unordered_map>

#include "robot_life_cpp/common/scene_taxonomy.hpp"
#include "robot_life_cpp/event_engine/arbitrator.hpp"
#include "robot_life_cpp/event_engine/scene_aggregator.hpp"
#include "robot_life_cpp/event_engine/stabilizer.hpp"
#include "robot_life_cpp/perception/deepstream_graph.hpp"
#include "robot_life_cpp/runtime/event_injector.hpp"
#include "robot_life_cpp/runtime/live_loop.hpp"

namespace robot_life_cpp::runtime {

struct RuntimeTuningProfile {
  std::string profile_name;
  LiveLoopConfig live_loop{};
  EventInjectorConfig event_injector{};
  event_engine::StabilizerRules stabilizer{};
  event_engine::SceneAggregatorRules aggregator{};
  event_engine::ArbitratorRules arbitrator{};
  common::SceneTaxonomyRules taxonomy{};
  bool share_preprocess{true};
  bool share_tracker{true};
  std::size_t max_detections_per_frame{4};
  std::unordered_map<perception::DeepStreamBranchId, bool> branch_enabled{};
  std::unordered_map<perception::DeepStreamBranchId, int> branch_intervals{};
};

bool load_runtime_tuning_profile(
    const std::filesystem::path& path,
    const std::string& profile_name,
    RuntimeTuningProfile* out,
    std::string* error = nullptr);

void apply_runtime_tuning_to_graph(
    const RuntimeTuningProfile& tuning,
    perception::DeepStreamGraphConfig* config);

class RuntimeTuningStore {
 public:
  explicit RuntimeTuningStore(std::filesystem::path path = {});

  bool load(const std::string& profile_name, std::string* error = nullptr);
  bool reload_if_changed(
      const std::string& profile_name,
      bool* reloaded = nullptr,
      std::string* error = nullptr);

  const std::filesystem::path& path() const;
  const std::optional<RuntimeTuningProfile>& current() const;

 private:
  std::filesystem::path path_;
  std::optional<RuntimeTuningProfile> current_{};
  std::filesystem::file_time_type last_write_time_{};
};

}  // namespace robot_life_cpp::runtime
