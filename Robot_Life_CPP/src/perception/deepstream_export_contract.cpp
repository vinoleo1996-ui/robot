#include "robot_life_cpp/perception/deepstream_export_contract.hpp"

#include <algorithm>

namespace robot_life_cpp::perception::deepstream_export_contract {

std::vector<std::string_view> required_export_payload_keys() {
  return {
      "camera_id",
      "frame_id",
      "track_id",
      "bbox",
      KEY_BRANCH_ID,
      KEY_BRANCH_NAME,
      KEY_PLUGIN,
      KEY_BINDING_STAGE,
      KEY_DEVICE,
      KEY_TRACK_KIND,
      KEY_EXPORTER_VERSION,
  };
}

std::vector<std::string_view> optional_export_payload_keys() {
  return {
      KEY_CLASS_ID,
      KEY_CLASS_NAME,
      KEY_TRACKER_SOURCE,
      KEY_CONFIDENCE,
      KEY_LANDMARKS,
      KEY_EMBEDDING_REF,
      KEY_MOTION_SCORE,
      KEY_SCENE_TAGS,
  };
}

std::vector<std::string_view> recommended_export_payload_keys() {
  auto keys = required_export_payload_keys();
  const auto optional = optional_export_payload_keys();
  keys.insert(keys.end(), optional.begin(), optional.end());
  return keys;
}

bool validate_export_payload_keys(
    const std::vector<std::string>& keys,
    std::vector<std::string>* missing_required) {
  bool ok = true;
  for (const auto required : required_export_payload_keys()) {
    const bool present = std::find(keys.begin(), keys.end(), std::string{required}) != keys.end();
    if (!present) {
      ok = false;
      if (missing_required != nullptr) {
        missing_required->push_back(std::string{required});
      }
    }
  }
  return ok;
}

}  // namespace robot_life_cpp::perception::deepstream_export_contract
