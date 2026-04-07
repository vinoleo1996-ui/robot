#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct EntityTrack {
  std::string track_id{};
  std::string track_kind{};
  double created_at{0.0};
  double last_seen_at{0.0};
  int detection_count{0};
  std::string last_detector{};
  std::string last_event_type{};
  std::string identity_hint{};
  std::string external_track_key{};
};

struct EntityTrackerSnapshot {
  std::size_t active_track_count{0};
  std::vector<EntityTrack> tracks{};
};

class EntityTracker {
 public:
  explicit EntityTracker(double person_ttl_s = 1.5, double object_ttl_s = 1.0);

  std::vector<std::pair<std::string, common::DetectionResult>> associate_batch(
      const std::vector<std::pair<std::string, common::DetectionResult>>& items,
      double now_mono_s = common::now_mono());

  EntityTrackerSnapshot snapshot(double now_mono_s = common::now_mono());

 private:
  static bool looks_like_ephemeral_target(const std::string& value);
  static std::string infer_modality(
      const std::string& pipeline_name,
      const common::DetectionResult& detection);
  static bool is_person_like_modality(const std::string& modality);
  static bool is_object_like_modality(const std::string& modality);
  static std::optional<std::string> make_external_track_key(
      const std::string& modality,
      const common::DetectionResult& detection,
      const common::Payload& payload);

  EntityTrack* resolve_track(
      const std::string& modality,
      const std::string& identity_hint,
      const std::optional<std::string>& external_track_key,
      bool allow_recent_fallback,
      double now_mono_s);

  EntityTrack& create_track(
      const std::string& kind,
      const std::string& identity_hint,
      double now_mono_s);

  void prune(double now_mono_s);

  double person_ttl_s_{1.5};
  double object_ttl_s_{1.0};
  std::unordered_map<std::string, EntityTrack> tracks_{};
  std::unordered_map<std::string, std::string> external_track_to_internal_{};
  int next_person_id_{1};
  int next_object_id_{1};
};

}  // namespace robot_life_cpp::event_engine
