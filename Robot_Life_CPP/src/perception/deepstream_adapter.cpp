#include "robot_life_cpp/perception/deepstream_adapter.hpp"

#include "robot_life_cpp/common/contracts.hpp"
#include "robot_life_cpp/common/visual_contract.hpp"
#include "robot_life_cpp/perception/deepstream_export_contract.hpp"

namespace robot_life_cpp::perception {

std::optional<common::DetectionResult> DeepStreamAdapter::adapt_detection(
    const bridge::DeepStreamEnvelope& envelope) {
  if (envelope.kind != bridge::DeepStreamEnvelope::Kind::Detection || !envelope.detection.has_value()) {
    return std::nullopt;
  }

  auto detection = *envelope.detection;
  if (detection.trace_id.empty()) {
    detection.trace_id = common::new_id();
  }
  if (detection.source.empty()) {
    detection.source = "deepstream";
  }
  if (detection.detector.empty()) {
    detection.detector = "deepstream";
  }
  detection.event_type = common::contracts::canonical_event_detected(detection.event_type);
  if (detection.timestamp <= 0.0) {
    detection.timestamp = common::now_wall();
  }

  auto& payload = detection.payload;
  const auto camera_key = std::string(common::visual_contract::KEY_CAMERA_ID);
  const auto frame_key = std::string(common::visual_contract::KEY_FRAME_ID);
  const auto track_key = std::string(common::visual_contract::KEY_TRACK_ID);
  const auto bbox_key = std::string(common::visual_contract::KEY_BBOX);

  if (!payload.contains(camera_key) || payload.at(camera_key).empty()) {
    payload[camera_key] = detection.source;
  }
  if (!payload.contains(frame_key) || payload.at(frame_key).empty()) {
    payload[frame_key] = detection.trace_id;
  }
  if (!payload.contains(track_key) || payload.at(track_key).empty()) {
    payload[track_key] = detection.detector + "_track_unknown";
  }
  if (!payload.contains(bbox_key) || payload.at(bbox_key).empty()) {
    return std::nullopt;
  }
  payload.try_emplace(
      std::string(deepstream_export_contract::KEY_EXPORTER_VERSION),
      "deepstream-export-contract/v1");

  const auto validation = common::visual_contract::validate_visual_detection(detection);
  if (!validation.ok) {
    return std::nullopt;
  }

  const auto signature =
      detection.source + "|" + detection.detector + "|" + detection.event_type + "|" + payload.at(frame_key) +
      "|" + payload.at(track_key);
  if (signature == last_signature_) {
    return std::nullopt;
  }
  last_signature_ = signature;
  return detection;
}

}  // namespace robot_life_cpp::perception
