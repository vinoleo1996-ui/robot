#include "robot_life_cpp/perception/deepstream_graph.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>
#include <string_view>
#include <unordered_map>
#include <utility>

#include "robot_life_cpp/common/contracts.hpp"
#include "robot_life_cpp/common/visual_contract.hpp"

namespace robot_life_cpp::perception {

namespace {
std::string trim_copy(std::string value) {
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(),
                           [](unsigned char c) { return !std::isspace(c); }));
  value.erase(std::find_if(value.rbegin(), value.rend(),
                           [](unsigned char c) { return !std::isspace(c); })
                  .base(),
              value.end());
  return value;
}

bool parse_bool(const std::string& value, bool fallback) {
  std::string normalized = value;
  std::transform(normalized.begin(), normalized.end(), normalized.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (normalized == "true" || normalized == "1" || normalized == "yes" || normalized == "on") {
    return true;
  }
  if (normalized == "false" || normalized == "0" || normalized == "no" || normalized == "off") {
    return false;
  }
  return fallback;
}

std::string lowercase_copy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

std::unordered_map<std::string, std::string> load_yaml_like(
    const std::filesystem::path& path,
    std::string* error) {
  std::unordered_map<std::string, std::string> out{};
  std::ifstream fin(path);
  if (!fin.good()) {
    if (error != nullptr) {
      *error = "cannot open graph config: " + path.string();
    }
    return out;
  }

  std::string line{};
  while (std::getline(fin, line)) {
    const auto no_comment = line.substr(0, line.find('#'));
    const auto pos = no_comment.find(':');
    if (pos == std::string::npos) {
      continue;
    }
    auto key = trim_copy(no_comment.substr(0, pos));
    auto value = trim_copy(no_comment.substr(pos + 1));
    if (!key.empty()) {
      out[key] = value;
    }
  }
  return out;
}

std::unordered_map<std::string, std::string> load_property_file(
    const std::filesystem::path& path,
    std::string* error) {
  std::unordered_map<std::string, std::string> out{};
  std::ifstream fin(path);
  if (!fin.good()) {
    if (error != nullptr) {
      *error = "cannot open model config: " + path.string();
    }
    return out;
  }

  std::string line{};
  while (std::getline(fin, line)) {
    const auto no_comment = trim_copy(line.substr(0, line.find('#')));
    if (no_comment.empty() || no_comment.front() == '[') {
      continue;
    }
    const auto pos = no_comment.find('=');
    if (pos == std::string::npos) {
      continue;
    }
    auto key = trim_copy(no_comment.substr(0, pos));
    auto value = trim_copy(no_comment.substr(pos + 1));
    if (!key.empty()) {
      out[key] = value;
    }
  }
  if (error != nullptr) {
    error->clear();
  }
  return out;
}

std::filesystem::path resolve_model_config_path(
    const std::string& raw_path,
    const std::filesystem::path& graph_config_path) {
  if (raw_path.empty()) {
    return {};
  }
  const auto candidate = std::filesystem::path{raw_path};
  if (candidate.is_absolute()) {
    return candidate;
  }
  if (std::filesystem::exists(candidate)) {
    return candidate;
  }
  if (graph_config_path.empty()) {
    return candidate;
  }
  const auto parent = graph_config_path.parent_path();
  if (parent.empty()) {
    return candidate;
  }
  const auto rooted_at_graph = parent / candidate;
  if (std::filesystem::exists(rooted_at_graph)) {
    return rooted_at_graph;
  }
  return candidate;
}

DeepStreamBranchConfig make_branch(DeepStreamBranchId id,
                                   std::string name,
                                   int interval_frames,
                                   std::string detector,
                                   std::string event_type,
                                   std::string track_kind,
                                   double confidence_hint,
                                   std::string plugin,
                                   std::string model_config_path,
                                   std::string binding_stage) {
  return {
      .id = id,
      .name = std::move(name),
      .enabled = true,
      .sample_interval_frames = interval_frames,
      .detector = std::move(detector),
      .event_type = std::move(event_type),
      .track_kind = std::move(track_kind),
      .confidence_hint = confidence_hint,
      .plugin = std::move(plugin),
      .model_config_path = std::move(model_config_path),
      .binding_stage = std::move(binding_stage),
      .device = "cuda:0",
  };
}

const DeepStreamBranchContract& branch_contract_impl(DeepStreamBranchId id) {
  static const std::vector<DeepStreamBranchContract> kContracts{
      {
          .id = DeepStreamBranchId::Face,
          .name = "face",
          .default_event_type = std::string(common::visual_contract::EVENT_FACE_DETECTED),
          .allowed_event_types = {
              std::string(common::visual_contract::EVENT_FACE_DETECTED),
              std::string(common::visual_contract::EVENT_FACE_IDENTITY_DETECTED),
              std::string(common::visual_contract::EVENT_FACE_ATTENTION_DETECTED),
          },
          .track_kind = "face",
          .default_plugin = "nvinfer",
          .binding_stage = "detect_track_embed",
          .scene_hint = "human_presence",
          .supports_shared_preprocess = true,
          .supports_shared_tracker = true,
          .required_model_properties = {
              "network-type",
              "labelfile-path",
              "model-engine-file",
              "batch-size",
              "gpu-id",
              "tracker-config-file",
          },
      },
      {
          .id = DeepStreamBranchId::PoseGesture,
          .name = "pose_gesture",
          .default_event_type = std::string(common::visual_contract::EVENT_POSE_DETECTED),
          .allowed_event_types = {
              std::string(common::visual_contract::EVENT_POSE_DETECTED),
              std::string(common::visual_contract::EVENT_GESTURE_DETECTED),
              std::string(common::visual_contract::EVENT_WAVE_DETECTED),
          },
          .track_kind = "person",
          .default_plugin = "nvinfer",
          .binding_stage = "detect_keypoints_gesture",
          .scene_hint = "body_pose",
          .supports_shared_preprocess = true,
          .supports_shared_tracker = true,
          .required_model_properties = {
              "network-type",
              "labelfile-path",
              "model-engine-file",
              "batch-size",
              "gpu-id",
          },
      },
      {
          .id = DeepStreamBranchId::Motion,
          .name = "motion",
          .default_event_type = std::string(common::visual_contract::EVENT_MOTION_DETECTED),
          .allowed_event_types = {
              std::string(common::visual_contract::EVENT_MOTION_DETECTED),
              std::string(common::visual_contract::EVENT_APPROACHING_DETECTED),
              std::string(common::visual_contract::EVENT_LEAVING_DETECTED),
          },
          .track_kind = "motion",
          .default_plugin = "custom_motion",
          .binding_stage = "frame_delta_motion",
          .scene_hint = "motion_alert",
          .supports_shared_preprocess = true,
          .supports_shared_tracker = false,
          .required_model_properties = {
              "network-type",
              "model-engine-file",
              "batch-size",
              "gpu-id",
              "motion-threshold",
          },
      },
      {
          .id = DeepStreamBranchId::SceneObject,
          .name = "scene_object",
          .default_event_type = std::string(common::visual_contract::EVENT_SCENE_CONTEXT_DETECTED),
          .allowed_event_types = {
              std::string(common::visual_contract::EVENT_SCENE_CONTEXT_DETECTED),
              std::string(common::visual_contract::EVENT_PERSON_PRESENT_DETECTED),
              std::string(common::visual_contract::EVENT_OBJECT_DETECTED),
          },
          .track_kind = "scene",
          .default_plugin = "nvinfer",
          .binding_stage = "detect_scene_context",
          .scene_hint = "generic_event",
          .supports_shared_preprocess = true,
          .supports_shared_tracker = true,
          .required_model_properties = {
              "network-type",
              "labelfile-path",
              "model-engine-file",
              "batch-size",
              "gpu-id",
              "group-classes",
          },
      },
  };

  const auto it = std::find_if(kContracts.begin(), kContracts.end(), [&](const auto& contract) {
    return contract.id == id;
  });
  return *it;
}

bool contains_value(const std::vector<std::string>& values, std::string_view needle) {
  return std::find(values.begin(), values.end(), needle) != values.end();
}

std::string payload_lookup(const common::Payload& payload, std::string_view key) {
  const auto it = payload.find(std::string(key));
  return it == payload.end() ? std::string{} : it->second;
}
}  // namespace

std::string to_string(DeepStreamBranchId id) {
  switch (id) {
    case DeepStreamBranchId::Face:
      return "face";
    case DeepStreamBranchId::PoseGesture:
      return "pose_gesture";
    case DeepStreamBranchId::Motion:
      return "motion";
    case DeepStreamBranchId::SceneObject:
      return "scene_object";
  }
  return "unknown";
}

std::optional<DeepStreamBranchId> deepstream_branch_id_from_string(const std::string& name) {
  if (name == "face") {
    return DeepStreamBranchId::Face;
  }
  if (name == "pose_gesture" || name == "pose") {
    return DeepStreamBranchId::PoseGesture;
  }
  if (name == "motion") {
    return DeepStreamBranchId::Motion;
  }
  if (name == "scene_object" || name == "scene") {
    return DeepStreamBranchId::SceneObject;
  }
  return std::nullopt;
}

const DeepStreamBranchContract& deepstream_branch_contract(DeepStreamBranchId id) {
  return branch_contract_impl(id);
}

std::string resolve_deepstream_branch_event_type(
    DeepStreamBranchId id,
    const common::Payload& payload,
    const std::string& fallback_event_type) {
  switch (id) {
    case DeepStreamBranchId::Face: {
      const auto attention_state =
          lowercase_copy(payload_lookup(payload, common::visual_contract::KEY_ATTENTION_STATE));
      if (!attention_state.empty() &&
          (attention_state == "looking_at_camera" || attention_state == "attentive" ||
           attention_state == "engaged")) {
        return std::string(common::visual_contract::EVENT_FACE_ATTENTION_DETECTED);
      }
      const auto identity_state =
          lowercase_copy(payload_lookup(payload, common::visual_contract::KEY_IDENTITY_STATE));
      if (!identity_state.empty()) {
        return std::string(common::visual_contract::EVENT_FACE_IDENTITY_DETECTED);
      }
      return std::string(common::visual_contract::EVENT_FACE_DETECTED);
    }
    case DeepStreamBranchId::PoseGesture: {
      const auto gesture_name = lowercase_copy(payload_lookup(payload, common::visual_contract::KEY_GESTURE_NAME));
      if (gesture_name.find("wave") != std::string::npos) {
        return std::string(common::visual_contract::EVENT_WAVE_DETECTED);
      }
      if (!gesture_name.empty()) {
        return std::string(common::visual_contract::EVENT_GESTURE_DETECTED);
      }
      return std::string(common::visual_contract::EVENT_POSE_DETECTED);
    }
    case DeepStreamBranchId::Motion: {
      const auto direction =
          lowercase_copy(payload_lookup(payload, common::visual_contract::KEY_MOTION_DIRECTION));
      if (direction == "approaching" || direction == "approach") {
        return std::string(common::visual_contract::EVENT_APPROACHING_DETECTED);
      }
      if (direction == "leaving" || direction == "departing") {
        return std::string(common::visual_contract::EVENT_LEAVING_DETECTED);
      }
      return std::string(common::visual_contract::EVENT_MOTION_DETECTED);
    }
    case DeepStreamBranchId::SceneObject: {
      const auto class_name = lowercase_copy(payload_lookup(payload, common::visual_contract::KEY_CLASS_NAME));
      if (class_name == "person" || class_name == "human") {
        return std::string(common::visual_contract::EVENT_PERSON_PRESENT_DETECTED);
      }
      if (!class_name.empty()) {
        return std::string(common::visual_contract::EVENT_OBJECT_DETECTED);
      }
      return std::string(common::visual_contract::EVENT_SCENE_CONTEXT_DETECTED);
    }
  }
  return common::contracts::canonical_event_detected(fallback_event_type);
}

std::string deepstream_scene_hint_for_event_type(const std::string& event_type) {
  const auto canonical = common::contracts::canonical_event_detected(event_type);
  if (canonical.find("face") != std::string::npos || canonical.find("person_present") != std::string::npos) {
    return "human_presence";
  }
  if (canonical.find("gesture") != std::string::npos || canonical.find("wave") != std::string::npos) {
    return "gesture_interaction";
  }
  if (canonical.find("motion") != std::string::npos || canonical.find("approaching") != std::string::npos ||
      canonical.find("leaving") != std::string::npos) {
    return "motion_alert";
  }
  if (canonical.find("pose") != std::string::npos) {
    return "body_pose";
  }
  return "generic_event";
}

DeepStreamGraphConfig default_deepstream_graph_config() {
  DeepStreamGraphConfig config{};
  config.graph_name = "deepstream_four_vision";
  config.share_preprocess = true;
  config.share_tracker = true;
  config.max_detections_per_frame = 4;
  config.branches = {
      make_branch(
          DeepStreamBranchId::Face,
          "face",
          1,
          "deepstream_face",
          std::string(common::visual_contract::EVENT_FACE_DETECTED),
          "face",
          0.94,
          "nvinfer",
          "models/deepstream/face/pgie_face.txt",
          "detect_track_embed"),
      make_branch(
          DeepStreamBranchId::PoseGesture,
          "pose_gesture",
          2,
          "deepstream_pose",
          std::string(common::visual_contract::EVENT_POSE_DETECTED),
          "person",
          0.92,
          "nvinfer",
          "models/deepstream/pose/pgie_pose.txt",
          "detect_keypoints_gesture"),
      make_branch(
          DeepStreamBranchId::Motion,
          "motion",
          1,
          "deepstream_motion",
          std::string(common::visual_contract::EVENT_MOTION_DETECTED),
          "motion",
          0.78,
          "custom_motion",
          "models/deepstream/motion/motion_config.txt",
          "frame_delta_motion"),
      make_branch(
          DeepStreamBranchId::SceneObject,
          "scene_object",
          3,
          "deepstream_scene",
          std::string(common::visual_contract::EVENT_SCENE_CONTEXT_DETECTED),
          "scene",
          0.89,
          "nvinfer",
          "models/deepstream/scene/pgie_scene.txt",
          "detect_scene_context"),
  };
  return config;
}

bool load_deepstream_graph_config(
    const std::filesystem::path& path,
    DeepStreamGraphConfig* out,
    std::string* error) {
  if (out == nullptr) {
    if (error != nullptr) {
      *error = "output config is null";
    }
    return false;
  }

  auto config = default_deepstream_graph_config();
  const auto kv = load_yaml_like(path, error);
  if (kv.empty() && !std::filesystem::exists(path)) {
    return false;
  }

  if (const auto it = kv.find("graph_name"); it != kv.end() && !it->second.empty()) {
    config.graph_name = it->second;
  }
  if (const auto it = kv.find("share_preprocess"); it != kv.end()) {
    config.share_preprocess = parse_bool(it->second, config.share_preprocess);
  }
  if (const auto it = kv.find("share_tracker"); it != kv.end()) {
    config.share_tracker = parse_bool(it->second, config.share_tracker);
  }
  if (const auto it = kv.find("max_detections_per_frame"); it != kv.end() && !it->second.empty()) {
    config.max_detections_per_frame = static_cast<std::size_t>(std::max(1, std::stoi(it->second)));
  }

  for (auto& branch : config.branches) {
    const auto prefix = "branch." + branch.name + ".";
    if (const auto it = kv.find(prefix + "enabled"); it != kv.end()) {
      branch.enabled = parse_bool(it->second, branch.enabled);
    }
    if (const auto it = kv.find(prefix + "sample_interval_frames"); it != kv.end() && !it->second.empty()) {
      branch.sample_interval_frames = std::max(1, std::stoi(it->second));
    }
    if (const auto it = kv.find(prefix + "detector"); it != kv.end() && !it->second.empty()) {
      branch.detector = it->second;
    }
    if (const auto it = kv.find(prefix + "event_type"); it != kv.end() && !it->second.empty()) {
      branch.event_type = it->second;
    }
    if (const auto it = kv.find(prefix + "track_kind"); it != kv.end() && !it->second.empty()) {
      branch.track_kind = it->second;
    }
    if (const auto it = kv.find(prefix + "confidence_hint"); it != kv.end() && !it->second.empty()) {
      branch.confidence_hint = std::stod(it->second);
    }
    if (const auto it = kv.find(prefix + "plugin"); it != kv.end() && !it->second.empty()) {
      branch.plugin = it->second;
    }
    if (const auto it = kv.find(prefix + "model_config_path"); it != kv.end() && !it->second.empty()) {
      branch.model_config_path = it->second;
    }
    if (const auto it = kv.find(prefix + "binding_stage"); it != kv.end() && !it->second.empty()) {
      branch.binding_stage = it->second;
    }
    if (const auto it = kv.find(prefix + "device"); it != kv.end() && !it->second.empty()) {
      branch.device = it->second;
    }
  }

  *out = std::move(config);
  if (error != nullptr) {
    error->clear();
  }
  return true;
}

DeepStreamExecutionPlan build_deepstream_execution_plan(
    const DeepStreamGraphConfig& config,
    const std::filesystem::path& graph_config_path) {
  DeepStreamExecutionPlan plan{};
  plan.graph_name = config.graph_name;
  plan.graph_config_path = graph_config_path;
  plan.share_preprocess = config.share_preprocess;
  plan.share_tracker = config.share_tracker;
  plan.max_detections_per_frame = config.max_detections_per_frame;
  plan.branches.reserve(config.branches.size());

  for (const auto& branch : config.branches) {
    const auto resolved_model_path = resolve_model_config_path(branch.model_config_path, graph_config_path);
    const auto& contract = deepstream_branch_contract(branch.id);
    DeepStreamBranchExecutionPlan branch_plan{};
    branch_plan.id = branch.id;
    branch_plan.name = branch.name;
    branch_plan.enabled = branch.enabled;
    branch_plan.sample_interval_frames = branch.sample_interval_frames;
    branch_plan.plugin = branch.plugin;
    branch_plan.model_config_path = resolved_model_path;
    branch_plan.binding_stage = branch.binding_stage;
    branch_plan.device = branch.device;
    branch_plan.uses_shared_preprocess = config.share_preprocess;
    branch_plan.uses_shared_tracker = config.share_tracker && contract.supports_shared_tracker;
    branch_plan.model_config_exists = !resolved_model_path.empty() && std::filesystem::exists(resolved_model_path);
    branch_plan.scene_hint = contract.scene_hint;
    branch_plan.allowed_event_types = contract.allowed_event_types;
    branch_plan.required_model_properties = contract.required_model_properties;
    plan.branches.push_back(branch_plan);

    if (!branch.enabled) {
      continue;
    }
    if (branch.plugin.empty()) {
      plan.errors.push_back("branch " + branch.name + " missing plugin");
    }
    if (branch.binding_stage.empty()) {
      plan.errors.push_back("branch " + branch.name + " missing binding_stage");
    }
    const auto canonical_event = common::contracts::canonical_event_detected(branch.event_type);
    if (!contains_value(contract.allowed_event_types, canonical_event)) {
      plan.errors.push_back(
          "branch " + branch.name + " unsupported event_type: " + canonical_event);
    }
    if (branch.model_config_path.empty()) {
      plan.errors.push_back("branch " + branch.name + " missing model_config_path");
    } else if (!branch_plan.model_config_exists) {
      plan.errors.push_back(
          "branch " + branch.name + " missing model config file: " + branch_plan.model_config_path.string());
    } else {
      std::string error{};
      const auto properties = load_property_file(branch_plan.model_config_path, &error);
      for (const auto& property : contract.required_model_properties) {
        const auto it = properties.find(property);
        if (it == properties.end() || it->second.empty()) {
          plan.branches.back().missing_model_properties.push_back(property);
        }
      }
      for (const auto& property : plan.branches.back().missing_model_properties) {
        plan.errors.push_back(
            "branch " + branch.name + " missing model property: " + property +
            " in " + branch_plan.model_config_path.string());
      }
    }
  }

  return plan;
}

bool deepstream_execution_plan_valid(const DeepStreamExecutionPlan& plan) {
  return plan.errors.empty() &&
         std::any_of(plan.branches.begin(), plan.branches.end(), [](const auto& branch) { return branch.enabled; });
}

std::string render_deepstream_app_config(const DeepStreamExecutionPlan& plan) {
  std::ostringstream out{};
  out << "# Autogenerated from graph_name=" << plan.graph_name << "\n";
  out << "[application]\n";
  out << "enable-perf-measurement=1\n";
  out << "perf-measurement-interval-sec=5\n\n";

  out << "[streammux]\n";
  out << "batch-size=" << std::max<std::size_t>(1, plan.max_detections_per_frame) << "\n";
  out << "live-source=1\n";
  out << "sync-inputs=0\n\n";

  int gie_index = 0;
  for (const auto& branch : plan.branches) {
    if (!branch.enabled) {
      continue;
    }
    out << "[branch-" << branch.name << "]\n";
    out << "enable=1\n";
    out << "plugin=" << branch.plugin << "\n";
    out << "sample-interval-frames=" << std::max(1, branch.sample_interval_frames) << "\n";
    out << "binding-stage=" << branch.binding_stage << "\n";
    out << "device=" << branch.device << "\n";
    out << "shared-preprocess=" << (branch.uses_shared_preprocess ? 1 : 0) << "\n";
    out << "shared-tracker=" << (branch.uses_shared_tracker ? 1 : 0) << "\n";
    out << "config-file=" << branch.model_config_path.string() << "\n";
    out << "gie-unique-id=" << (++gie_index) << "\n\n";
  }

  return out.str();
}

DeepStreamGraphConfig DeepStreamFourVisionGraph::default_config() {
  return default_deepstream_graph_config();
}

DeepStreamFourVisionGraph::DeepStreamFourVisionGraph(DeepStreamGraphConfig config) {
  if (config.branches.empty()) {
    config = default_config();
  }
  if (config.max_detections_per_frame == 0) {
    config.max_detections_per_frame = 1;
  }
  config_ = std::move(config);
  stats_.graph_name = config_.graph_name;
  sync_branch_stats_from_config();
}

const DeepStreamGraphConfig& DeepStreamFourVisionGraph::config() const { return config_; }

const std::vector<DeepStreamBranchConfig>& DeepStreamFourVisionGraph::branch_configs() const {
  return config_.branches;
}

std::vector<DeepStreamBranchConfig> DeepStreamFourVisionGraph::enabled_branches() const {
  std::vector<DeepStreamBranchConfig> out{};
  for (const auto& branch : config_.branches) {
    if (branch.enabled) {
      out.push_back(branch);
    }
  }
  return out;
}

bool DeepStreamFourVisionGraph::set_share_preprocess(bool enabled) {
  config_.share_preprocess = enabled;
  return true;
}

bool DeepStreamFourVisionGraph::set_share_tracker(bool enabled) {
  config_.share_tracker = enabled;
  return true;
}

bool DeepStreamFourVisionGraph::set_max_detections_per_frame(std::size_t max_detections) {
  if (max_detections == 0) {
    return false;
  }
  config_.max_detections_per_frame = max_detections;
  return true;
}

bool DeepStreamFourVisionGraph::set_branch_enabled(DeepStreamBranchId id, bool enabled) {
  auto* branch = find_branch(id);
  auto* branch_stats = find_branch_stats(id);
  if (branch == nullptr || branch_stats == nullptr) {
    return false;
  }
  branch->enabled = enabled;
  branch_stats->enabled = enabled;
  refresh_enabled_branch_count();
  return true;
}

bool DeepStreamFourVisionGraph::set_branch_interval(DeepStreamBranchId id, int interval_frames) {
  if (interval_frames < 1) {
    return false;
  }
  auto* branch = find_branch(id);
  if (branch == nullptr) {
    return false;
  }
  branch->sample_interval_frames = interval_frames;
  return true;
}

std::vector<common::DetectionResult> DeepStreamFourVisionGraph::ingest_frame(
    std::string source,
    int frame_index) {
  ++stats_.frames_ingested;
  if (config_.share_preprocess) {
    ++stats_.shared_preprocess_runs;
  }
  if (config_.share_tracker) {
    ++stats_.shared_tracker_updates;
  }

  std::vector<common::DetectionResult> detections{};
  detections.reserve(config_.branches.size());

  for (const auto& branch : config_.branches) {
    auto* branch_stats = find_branch_stats(branch.id);
    if (branch_stats == nullptr) {
      continue;
    }
    ++branch_stats->frames_seen;

    if (!branch.enabled) {
      ++branch_stats->frames_skipped_disabled;
      ++stats_.disabled_branch_hits;
      continue;
    }

    if (branch.sample_interval_frames > 1 && (frame_index % branch.sample_interval_frames) != 0) {
      ++branch_stats->frames_skipped_sampling;
      ++stats_.sampled_branch_hits;
      continue;
    }

    if (detections.size() >= config_.max_detections_per_frame) {
      ++stats_.detections_dropped_due_to_cap;
      continue;
    }

    ++branch_stats->frames_selected;
    auto detection = build_detection(
        branch,
        source,
        frame_index,
        stats_.shared_preprocess_runs,
        stats_.shared_tracker_updates);
    branch_stats->detections_emitted += 1;
    branch_stats->last_frame_index = frame_index;
    branch_stats->last_source = detection.source;
    branch_stats->last_event_type = detection.event_type;
    branch_stats->last_detector = detection.detector;
    branch_stats->last_confidence = detection.confidence;
    detections.push_back(std::move(detection));
  }

  stats_.detections_emitted += detections.size();
  refresh_enabled_branch_count();
  return detections;
}

DeepStreamGraphStats DeepStreamFourVisionGraph::stats() const { return stats_; }

DeepStreamBranchConfig* DeepStreamFourVisionGraph::find_branch(DeepStreamBranchId id) {
  const auto it = std::find_if(config_.branches.begin(), config_.branches.end(), [&](const auto& branch) {
    return branch.id == id;
  });
  return it == config_.branches.end() ? nullptr : &(*it);
}

DeepStreamBranchStats* DeepStreamFourVisionGraph::find_branch_stats(DeepStreamBranchId id) {
  const auto it = std::find_if(stats_.branches.begin(), stats_.branches.end(), [&](const auto& branch) {
    return branch.id == id;
  });
  return it == stats_.branches.end() ? nullptr : &(*it);
}

common::DetectionResult DeepStreamFourVisionGraph::build_detection(
    const DeepStreamBranchConfig& branch,
    std::string source,
    int frame_index,
    std::size_t shared_preprocess_seq,
    std::size_t shared_tracker_seq) const {
  common::DetectionResult detection{};
  detection.trace_id = common::new_id();
  detection.source = std::move(source);
  detection.detector = branch.detector;
  detection.timestamp = common::now_wall();
  detection.confidence = branch.confidence_hint;
  detection.payload = {
      {std::string(common::visual_contract::KEY_CAMERA_ID), detection.source},
      {std::string(common::visual_contract::KEY_FRAME_ID), std::to_string(frame_index)},
      {std::string(common::visual_contract::KEY_TRACK_ID), branch.track_kind + "_track_" + std::to_string(frame_index % 4)},
      {std::string(common::visual_contract::KEY_BBOX), "10,20,120,160"},
      {"branch", branch.name},
      {"branch_id", to_string(branch.id)},
      {"branch_name", branch.name},
      {"branch_sample_interval_frames", std::to_string(branch.sample_interval_frames)},
      {"shared_preprocess_seq", std::to_string(shared_preprocess_seq)},
      {"shared_tracker_seq", std::to_string(shared_tracker_seq)},
      {"track_kind", branch.track_kind},
      {"plugin", branch.plugin},
      {"model_config_path", branch.model_config_path},
      {"binding_stage", branch.binding_stage},
      {"device", branch.device},
      {std::string(common::visual_contract::KEY_SCENE_HINT), deepstream_branch_contract(branch.id).scene_hint},
  };

  switch (branch.id) {
    case DeepStreamBranchId::Face:
      detection.payload[std::string(common::visual_contract::KEY_CLASS_NAME)] = "face";
      detection.payload[std::string(common::visual_contract::KEY_EMBEDDING_REF)] =
          "face_embedding_" + std::to_string(frame_index);
      if ((frame_index % 2) == 0) {
        detection.payload[std::string(common::visual_contract::KEY_IDENTITY_STATE)] = "familiar";
      } else {
        detection.payload[std::string(common::visual_contract::KEY_ATTENTION_STATE)] = "looking_at_camera";
      }
      break;
    case DeepStreamBranchId::PoseGesture:
      detection.payload[std::string(common::visual_contract::KEY_CLASS_NAME)] = "person";
      detection.payload[std::string(common::visual_contract::KEY_LANDMARKS)] = "nose:0.45,0.18";
      if ((frame_index % 2) == 0) {
        detection.payload[std::string(common::visual_contract::KEY_GESTURE_NAME)] = "wave";
      }
      break;
    case DeepStreamBranchId::Motion:
      detection.payload[std::string(common::visual_contract::KEY_MOTION_SCORE)] =
          std::to_string(0.55 + static_cast<double>(frame_index % 10) * 0.03);
      detection.payload[std::string(common::visual_contract::KEY_MOTION_DIRECTION)] =
          (frame_index % 2) == 0 ? "approaching" : "leaving";
      break;
    case DeepStreamBranchId::SceneObject:
      detection.payload[std::string(common::visual_contract::KEY_CLASS_NAME)] =
          (frame_index % 2) == 0 ? "person" : "animal";
      detection.payload[std::string(common::visual_contract::KEY_SCENE_TAGS)] = "person,desk,monitor";
      break;
  }
  detection.event_type = resolve_deepstream_branch_event_type(branch.id, detection.payload, branch.event_type);
  detection.payload[std::string(common::visual_contract::KEY_SCENE_HINT)] =
      deepstream_scene_hint_for_event_type(detection.event_type);
  return detection;
}

void DeepStreamFourVisionGraph::sync_branch_stats_from_config() {
  stats_.branches.clear();
  stats_.branches.reserve(config_.branches.size());
  for (const auto& branch : config_.branches) {
    stats_.branches.push_back({
        .id = branch.id,
        .name = branch.name,
        .enabled = branch.enabled,
        .frames_seen = 0,
        .frames_selected = 0,
        .frames_skipped_disabled = 0,
        .frames_skipped_sampling = 0,
        .detections_emitted = 0,
        .last_frame_index = -1,
        .last_source = {},
        .last_event_type = {},
        .last_detector = {},
        .last_confidence = 0.0,
    });
  }
  refresh_enabled_branch_count();
}

void DeepStreamFourVisionGraph::refresh_enabled_branch_count() {
  stats_.enabled_branch_count = std::count_if(config_.branches.begin(), config_.branches.end(), [](const auto& branch) {
    return branch.enabled;
  });
}

}  // namespace robot_life_cpp::perception
