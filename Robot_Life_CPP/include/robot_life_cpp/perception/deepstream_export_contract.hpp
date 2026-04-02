#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace robot_life_cpp::perception::deepstream_export_contract {

inline constexpr std::string_view KEY_BRANCH_ID = "branch_id";
inline constexpr std::string_view KEY_BRANCH_NAME = "branch_name";
inline constexpr std::string_view KEY_PLUGIN = "plugin";
inline constexpr std::string_view KEY_BINDING_STAGE = "binding_stage";
inline constexpr std::string_view KEY_DEVICE = "device";
inline constexpr std::string_view KEY_CLASS_ID = "class_id";
inline constexpr std::string_view KEY_CLASS_NAME = "class_name";
inline constexpr std::string_view KEY_TRACK_KIND = "track_kind";
inline constexpr std::string_view KEY_TRACKER_SOURCE = "tracker_source";
inline constexpr std::string_view KEY_CONFIDENCE = "confidence";
inline constexpr std::string_view KEY_LANDMARKS = "landmarks";
inline constexpr std::string_view KEY_EMBEDDING_REF = "embedding_ref";
inline constexpr std::string_view KEY_MOTION_SCORE = "motion_score";
inline constexpr std::string_view KEY_SCENE_TAGS = "scene_tags";
inline constexpr std::string_view KEY_EXPORTER_VERSION = "exporter_version";

std::vector<std::string_view> required_export_payload_keys();
std::vector<std::string_view> optional_export_payload_keys();
std::vector<std::string_view> recommended_export_payload_keys();
bool validate_export_payload_keys(
    const std::vector<std::string>& keys,
    std::vector<std::string>* missing_required = nullptr);

}  // namespace robot_life_cpp::perception::deepstream_export_contract
