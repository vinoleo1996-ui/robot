#pragma once

#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

struct TargetGovernorRules {
  double familiar_face_cooldown_s{1800.0};
  double stranger_face_cooldown_s{1800.0};
  double gesture_pose_cooldown_s{30.0};
  double special_audio_cooldown_s{30.0};
  double moving_object_cooldown_s{30.0};
  double attention_probe_cooldown_s{30.0};
  double active_target_hold_s{6.0};
  double special_audio_preempt_s{2.0};
  double gc_window_s{7200.0};
};

struct TargetGovernorSnapshot {
  std::optional<std::string> active_target_id{};
  std::optional<std::string> active_scene_type{};
  common::EventPriority active_priority{common::EventPriority::P3};
  double active_remaining_s{0.0};
  double special_audio_preempt_remaining_s{0.0};
  std::size_t tracked_face_bindings{0};
  std::size_t tracked_dedupe_entries{0};
};

class TargetGovernor {
 public:
  explicit TargetGovernor(TargetGovernorRules rules = {});

  void reconfigure(TargetGovernorRules rules);
  void reset();

  std::optional<common::RawEvent> preprocess(
      common::RawEvent event,
      double now_mono_s = common::now_mono());

  void record_decision(
      const common::ArbitrationResult& decision,
      double now_mono_s = common::now_mono());

  std::optional<std::string> active_target_id(double now_mono_s = common::now_mono());
  TargetGovernorSnapshot snapshot(double now_mono_s = common::now_mono());

 private:
  static std::optional<std::string> payload_value(const common::Payload& payload, const std::string& key);
  static std::string normalize_token(std::string value);
  static bool contains_token(const std::string& value, const std::string& token);
  static bool is_face_event(const std::string& event_type);
  static bool is_familiar_face_event(const std::string& event_type);
  static bool is_stranger_face_event(const std::string& event_type);
  static bool is_gesture_pose_event(const std::string& event_type);
  static bool is_special_audio_event(const std::string& event_type);
  static bool is_moving_object_event(const std::string& event_type);
  static bool is_attention_probe_event(const std::string& event_type);
  static common::EventPriority suggested_priority(const std::string& event_type, common::EventPriority fallback);
  static std::optional<std::string> canonical_target_id(const common::RawEvent& event);

  std::optional<std::string> resolve_face_id(const common::RawEvent& event, const std::string& target_id) const;
  void maybe_bind_face_identity(const common::RawEvent& event, const std::string& target_id);
  double cooldown_for(const common::RawEvent& event) const;
  std::string dedupe_key_for(
      const common::RawEvent& event,
      const std::string& target_id,
      const std::optional<std::string>& face_id) const;
  void refresh_preempt(double now_mono_s);
  void gc(double now_mono_s);

  mutable std::mutex mu_{};
  TargetGovernorRules rules_{};
  std::unordered_map<std::string, double> last_emit_by_key_{};
  std::unordered_map<std::string, std::string> track_face_bindings_{};
  std::optional<std::string> active_target_id_{};
  std::optional<std::string> active_scene_type_{};
  common::EventPriority active_priority_{common::EventPriority::P3};
  double active_until_{0.0};
  std::optional<std::string> preempted_target_id_{};
  std::optional<std::string> preempted_scene_type_{};
  common::EventPriority preempted_priority_{common::EventPriority::P3};
  double preempted_active_until_{0.0};
  double special_audio_preempt_until_{0.0};
  std::size_t gc_counter_{0};
};

}  // namespace robot_life_cpp::runtime
