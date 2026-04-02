#pragma once

#include <optional>
#include <string>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::perception {

struct DeepStreamObjectMetadata {
  std::string branch_id;
  std::string branch_name;
  std::string detector;
  std::string event_type;
  std::string plugin;
  std::string binding_stage;
  std::string device;
  std::string track_kind;
  std::string track_id;
  std::string bbox;
  double confidence{0.0};
  std::optional<int> class_id{};
  std::optional<std::string> class_name{};
  std::optional<std::string> tracker_source{};
  std::optional<std::string> landmarks{};
  std::optional<std::string> embedding_ref{};
  std::optional<std::string> identity_state{};
  std::optional<std::string> attention_state{};
  std::optional<std::string> gesture_name{};
  std::optional<std::string> motion_score{};
  std::optional<std::string> motion_direction{};
  std::optional<std::string> scene_tags{};
  std::optional<std::string> trace_id{};
};

struct DeepStreamFrameMetadata {
  std::string source;
  std::string camera_id;
  std::string frame_id;
  double timestamp{0.0};
  std::vector<DeepStreamObjectMetadata> objects{};
};

class DeepStreamExporter {
 public:
  std::optional<common::DetectionResult> export_object(
      const DeepStreamFrameMetadata& frame,
      const DeepStreamObjectMetadata& object) const;
  std::vector<std::string> export_frame_lines(const DeepStreamFrameMetadata& frame) const;
};

}  // namespace robot_life_cpp::perception
