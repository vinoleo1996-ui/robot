#include "robot_life_cpp/perception/deepstream_exporter.hpp"

#include <cctype>
#include <unordered_set>

#include "robot_life_cpp/bridge/deepstream_protocol.hpp"
#include "robot_life_cpp/common/contracts.hpp"
#include "robot_life_cpp/common/visual_contract.hpp"
#include "robot_life_cpp/perception/deepstream_export_contract.hpp"
#include "robot_life_cpp/perception/deepstream_graph.hpp"

namespace robot_life_cpp::perception {

namespace {

bool is_valid_bbox_format(const std::string& bbox) {
  if (bbox.empty()) {
    return false;
  }
  int part_count = 0;
  std::size_t start = 0;
  while (start <= bbox.size()) {
    const auto end = bbox.find(',', start);
    const auto token = bbox.substr(start, end == std::string::npos ? std::string::npos : end - start);
    if (token.empty()) {
      return false;
    }
    bool has_digit = false;
    for (const char ch : token) {
      if (std::isdigit(static_cast<unsigned char>(ch))) {
        has_digit = true;
        continue;
      }
      if (ch == '.' || ch == '-' || ch == '+') {
        continue;
      }
      return false;
    }
    if (!has_digit) {
      return false;
    }
    ++part_count;
    if (end == std::string::npos) {
      break;
    }
    start = end + 1;
  }
  return part_count == 4;
}

std::string object_signature(const DeepStreamFrameMetadata& frame, const DeepStreamObjectMetadata& object) {
  return frame.camera_id + "|" + frame.frame_id + "|" + object.branch_id + "|" + object.track_id + "|" +
         object.event_type + "|" + object.bbox;
}

}  // namespace

std::optional<common::DetectionResult> DeepStreamExporter::export_object(
    const DeepStreamFrameMetadata& frame,
    const DeepStreamObjectMetadata& object) const {
  if (frame.camera_id.empty() || frame.frame_id.empty() || object.bbox.empty() || object.track_id.empty() ||
      object.branch_id.empty() || object.branch_name.empty() || object.plugin.empty() ||
      object.binding_stage.empty() || object.device.empty() || object.track_kind.empty()) {
    return std::nullopt;
  }
  if (!is_valid_bbox_format(object.bbox)) {
    return std::nullopt;
  }

  common::DetectionResult detection{};
  detection.trace_id = object.trace_id.value_or(common::new_id());
  detection.source = frame.source.empty() ? frame.camera_id : frame.source;
  detection.detector = object.detector.empty() ? "deepstream" : object.detector;
  detection.timestamp = frame.timestamp > 0.0 ? frame.timestamp : common::now_wall();
  detection.confidence = object.confidence;
  detection.payload = {
      {std::string(common::visual_contract::KEY_CAMERA_ID), frame.camera_id},
      {std::string(common::visual_contract::KEY_FRAME_ID), frame.frame_id},
      {std::string(common::visual_contract::KEY_TRACK_ID), object.track_id},
      {std::string(common::visual_contract::KEY_BBOX), object.bbox},
      {std::string(deepstream_export_contract::KEY_BRANCH_ID), object.branch_id},
      {std::string(deepstream_export_contract::KEY_BRANCH_NAME), object.branch_name},
      {std::string(deepstream_export_contract::KEY_PLUGIN), object.plugin},
      {std::string(deepstream_export_contract::KEY_BINDING_STAGE), object.binding_stage},
      {std::string(deepstream_export_contract::KEY_DEVICE), object.device},
      {std::string(deepstream_export_contract::KEY_TRACK_KIND), object.track_kind},
      {std::string(deepstream_export_contract::KEY_EXPORTER_VERSION), "deepstream-export-contract/v1"},
  };

  if (object.class_id.has_value()) {
    detection.payload[std::string(deepstream_export_contract::KEY_CLASS_ID)] = std::to_string(*object.class_id);
  }
  if (object.class_name.has_value()) {
    detection.payload[std::string(deepstream_export_contract::KEY_CLASS_NAME)] = *object.class_name;
  }
  if (object.tracker_source.has_value()) {
    detection.payload[std::string(deepstream_export_contract::KEY_TRACKER_SOURCE)] = *object.tracker_source;
  }
  if (object.landmarks.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_LANDMARKS)] = *object.landmarks;
  }
  if (object.embedding_ref.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_EMBEDDING_REF)] = *object.embedding_ref;
  }
  if (object.identity_state.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_IDENTITY_STATE)] = *object.identity_state;
  }
  if (object.attention_state.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_ATTENTION_STATE)] = *object.attention_state;
  }
  if (object.gesture_name.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_GESTURE_NAME)] = *object.gesture_name;
  }
  if (object.motion_score.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_MOTION_SCORE)] = *object.motion_score;
  }
  if (object.motion_direction.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_MOTION_DIRECTION)] = *object.motion_direction;
  }
  if (object.scene_tags.has_value()) {
    detection.payload[std::string(common::visual_contract::KEY_SCENE_TAGS)] = *object.scene_tags;
  }
  if (const auto branch_id = deepstream_branch_id_from_string(object.branch_id); branch_id.has_value()) {
    detection.event_type =
        resolve_deepstream_branch_event_type(*branch_id, detection.payload, object.event_type);
    detection.payload[std::string(common::visual_contract::KEY_SCENE_HINT)] =
        deepstream_scene_hint_for_event_type(detection.event_type);
  } else {
    detection.event_type = common::contracts::canonical_event_detected(object.event_type);
  }
  return detection;
}

std::vector<std::string> DeepStreamExporter::export_frame_lines(const DeepStreamFrameMetadata& frame) const {
  std::vector<std::string> lines{};
  lines.reserve(frame.objects.size());
  std::unordered_set<std::string> signatures{};
  for (const auto& object : frame.objects) {
    const auto signature = object_signature(frame, object);
    if (!signatures.insert(signature).second) {
      continue;
    }
    const auto detection = export_object(frame, object);
    if (!detection.has_value()) {
      continue;
    }
    lines.push_back(bridge::encode_detection_line(*detection));
  }
  return lines;
}

}  // namespace robot_life_cpp::perception
