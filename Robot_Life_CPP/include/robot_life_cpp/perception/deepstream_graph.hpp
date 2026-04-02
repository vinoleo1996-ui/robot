#pragma once

#include <filesystem>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::perception {

enum class DeepStreamBranchId : std::uint8_t {
  Face = 0,
  PoseGesture = 1,
  Motion = 2,
  SceneObject = 3,
};

struct DeepStreamBranchConfig {
  DeepStreamBranchId id{DeepStreamBranchId::Face};
  std::string name;
  bool enabled{true};
  int sample_interval_frames{1};
  std::string detector;
  std::string event_type;
  std::string track_kind{"object"};
  double confidence_hint{0.9};
  std::string plugin{"nvinfer"};
  std::string model_config_path;
  std::string binding_stage;
  std::string device{"cuda:0"};
};

struct DeepStreamGraphConfig {
  std::string graph_name{"deepstream_four_vision"};
  bool share_preprocess{true};
  bool share_tracker{true};
  std::size_t max_detections_per_frame{4};
  std::vector<DeepStreamBranchConfig> branches{};
};

struct DeepStreamBranchStats {
  DeepStreamBranchId id{DeepStreamBranchId::Face};
  std::string name;
  bool enabled{true};
  std::size_t frames_seen{0};
  std::size_t frames_selected{0};
  std::size_t frames_skipped_disabled{0};
  std::size_t frames_skipped_sampling{0};
  std::size_t detections_emitted{0};
  int last_frame_index{-1};
  std::string last_source;
  std::string last_event_type;
  std::string last_detector;
  double last_confidence{0.0};
};

struct DeepStreamGraphStats {
  std::string graph_name;
  std::size_t frames_ingested{0};
  std::size_t shared_preprocess_runs{0};
  std::size_t shared_tracker_updates{0};
  std::size_t detections_emitted{0};
  std::size_t detections_dropped_due_to_cap{0};
  std::size_t disabled_branch_hits{0};
  std::size_t sampled_branch_hits{0};
  std::size_t enabled_branch_count{0};
  std::vector<DeepStreamBranchStats> branches{};
};

struct DeepStreamBranchExecutionPlan {
  DeepStreamBranchId id{DeepStreamBranchId::Face};
  std::string name;
  bool enabled{true};
  int sample_interval_frames{1};
  std::string plugin;
  std::filesystem::path model_config_path;
  std::string binding_stage;
  std::string device;
  bool uses_shared_preprocess{true};
  bool uses_shared_tracker{true};
  bool model_config_exists{false};
  std::string scene_hint;
  std::vector<std::string> allowed_event_types{};
  std::vector<std::string> required_model_properties{};
  std::vector<std::string> missing_model_properties{};
};

struct DeepStreamBranchContract {
  DeepStreamBranchId id{DeepStreamBranchId::Face};
  std::string name;
  std::string default_event_type;
  std::vector<std::string> allowed_event_types{};
  std::string track_kind;
  std::string default_plugin;
  std::string binding_stage;
  std::string scene_hint;
  bool supports_shared_preprocess{true};
  bool supports_shared_tracker{true};
  std::vector<std::string> required_model_properties{};
};

struct DeepStreamExecutionPlan {
  std::string graph_name;
  std::filesystem::path graph_config_path;
  bool share_preprocess{true};
  bool share_tracker{true};
  std::size_t max_detections_per_frame{4};
  std::vector<DeepStreamBranchExecutionPlan> branches{};
  std::vector<std::string> errors{};
};

class DeepStreamFourVisionGraph {
 public:
  explicit DeepStreamFourVisionGraph(DeepStreamGraphConfig config = {});

  const DeepStreamGraphConfig& config() const;
  const std::vector<DeepStreamBranchConfig>& branch_configs() const;
  std::vector<DeepStreamBranchConfig> enabled_branches() const;
  bool set_share_preprocess(bool enabled);
  bool set_share_tracker(bool enabled);
  bool set_max_detections_per_frame(std::size_t max_detections);
  bool set_branch_enabled(DeepStreamBranchId id, bool enabled);
  bool set_branch_interval(DeepStreamBranchId id, int interval_frames);
  std::vector<common::DetectionResult> ingest_frame(std::string source, int frame_index);
  DeepStreamGraphStats stats() const;

 private:
  static DeepStreamGraphConfig default_config();
  DeepStreamBranchConfig* find_branch(DeepStreamBranchId id);
  DeepStreamBranchStats* find_branch_stats(DeepStreamBranchId id);
  common::DetectionResult build_detection(
      const DeepStreamBranchConfig& branch,
      std::string source,
      int frame_index,
      std::size_t shared_preprocess_seq,
      std::size_t shared_tracker_seq) const;
  void sync_branch_stats_from_config();
  void refresh_enabled_branch_count();

  DeepStreamGraphConfig config_{};
  DeepStreamGraphStats stats_{};
};

std::string to_string(DeepStreamBranchId id);
std::optional<DeepStreamBranchId> deepstream_branch_id_from_string(const std::string& name);
const DeepStreamBranchContract& deepstream_branch_contract(DeepStreamBranchId id);
std::string resolve_deepstream_branch_event_type(
    DeepStreamBranchId id,
    const common::Payload& payload,
    const std::string& fallback_event_type);
std::string deepstream_scene_hint_for_event_type(const std::string& event_type);
DeepStreamGraphConfig default_deepstream_graph_config();
bool load_deepstream_graph_config(
    const std::filesystem::path& path,
    DeepStreamGraphConfig* out,
    std::string* error = nullptr);
DeepStreamExecutionPlan build_deepstream_execution_plan(
    const DeepStreamGraphConfig& config,
    const std::filesystem::path& graph_config_path = {});
bool deepstream_execution_plan_valid(const DeepStreamExecutionPlan& plan);
std::string render_deepstream_app_config(const DeepStreamExecutionPlan& plan);

}  // namespace robot_life_cpp::perception
