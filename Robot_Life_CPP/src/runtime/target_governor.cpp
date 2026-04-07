#include "robot_life_cpp/runtime/target_governor.hpp"

#include <algorithm>
#include <cctype>

namespace robot_life_cpp::runtime {

namespace {

std::string lower_copy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
  return value;
}

}  // namespace

TargetGovernor::TargetGovernor(TargetGovernorRules rules) : rules_(std::move(rules)) {}

void TargetGovernor::reconfigure(TargetGovernorRules rules) {
  std::lock_guard<std::mutex> lock(mu_);
  rules_ = std::move(rules);
}

void TargetGovernor::reset() {
  std::lock_guard<std::mutex> lock(mu_);
  last_emit_by_key_.clear();
  track_face_bindings_.clear();
  active_target_id_.reset();
  active_scene_type_.reset();
  active_priority_ = common::EventPriority::P3;
  active_until_ = 0.0;
  preempted_target_id_.reset();
  preempted_scene_type_.reset();
  preempted_priority_ = common::EventPriority::P3;
  preempted_active_until_ = 0.0;
  special_audio_preempt_until_ = 0.0;
  gc_counter_ = 0;
}

std::optional<common::RawEvent> TargetGovernor::preprocess(
    common::RawEvent event,
    double now_mono_s) {
  std::lock_guard<std::mutex> lock(mu_);
  refresh_preempt(now_mono_s);

  const auto target_id_opt = canonical_target_id(event);
  const auto target_id = target_id_opt.value_or("global_target");
  event.payload["target_id"] = target_id;

  maybe_bind_face_identity(event, target_id);
  const auto face_id = resolve_face_id(event, target_id);
  if (face_id.has_value()) {
    event.payload["face_id"] = *face_id;
  }

  event.priority = suggested_priority(event.event_type, event.priority);

  if (active_target_id_.has_value() &&
      now_mono_s < active_until_ &&
      (event.priority == common::EventPriority::P2 || event.priority == common::EventPriority::P3) &&
      target_id != *active_target_id_ &&
      !is_special_audio_event(event.event_type)) {
    return std::nullopt;
  }

  const auto cooldown_s = cooldown_for(event);
  if (cooldown_s > 0.0) {
    const auto dedupe_key = dedupe_key_for(event, target_id, face_id);
    if (const auto it = last_emit_by_key_.find(dedupe_key);
        it != last_emit_by_key_.end() && (now_mono_s - it->second) < cooldown_s) {
      return std::nullopt;
    }
    last_emit_by_key_[dedupe_key] = now_mono_s;

    event.cooldown_key = event.event_type + ":" + (face_id.has_value() ? *face_id : target_id);
  }

  gc(now_mono_s);
  return event;
}

void TargetGovernor::record_decision(
    const common::ArbitrationResult& decision,
    double now_mono_s) {
  std::lock_guard<std::mutex> lock(mu_);
  refresh_preempt(now_mono_s);

  if (!decision.target_id.has_value() || decision.target_id->empty()) {
    return;
  }

  const auto hold_s = std::max(
      rules_.active_target_hold_s,
      (decision.priority == common::EventPriority::P0 || decision.priority == common::EventPriority::P1) ? 4.0 :
                                                                                                            0.0);

  if (decision.scene_type.has_value() && *decision.scene_type == "special_audio_attention_scene") {
    preempted_target_id_ = active_target_id_;
    preempted_scene_type_ = active_scene_type_;
    preempted_priority_ = active_priority_;
    preempted_active_until_ = active_until_;

    active_target_id_ = decision.target_id;
    active_scene_type_ = decision.scene_type;
    active_priority_ = decision.priority;
    active_until_ = now_mono_s + rules_.special_audio_preempt_s;
    special_audio_preempt_until_ = active_until_;
    return;
  }

  active_target_id_ = decision.target_id;
  active_scene_type_ = decision.scene_type;
  active_priority_ = decision.priority;
  active_until_ = now_mono_s + hold_s;
}

std::optional<std::string> TargetGovernor::active_target_id(double now_mono_s) {
  std::lock_guard<std::mutex> lock(mu_);
  refresh_preempt(now_mono_s);
  if (!active_target_id_.has_value() || now_mono_s >= active_until_) {
    return std::nullopt;
  }
  return active_target_id_;
}

TargetGovernorSnapshot TargetGovernor::snapshot(double now_mono_s) {
  std::lock_guard<std::mutex> lock(mu_);
  refresh_preempt(now_mono_s);

  TargetGovernorSnapshot out{};
  if (active_target_id_.has_value() && now_mono_s < active_until_) {
    out.active_target_id = active_target_id_;
    out.active_scene_type = active_scene_type_;
    out.active_priority = active_priority_;
    out.active_remaining_s = std::max(0.0, active_until_ - now_mono_s);
  }
  out.special_audio_preempt_remaining_s = std::max(0.0, special_audio_preempt_until_ - now_mono_s);
  out.tracked_face_bindings = track_face_bindings_.size();
  out.tracked_dedupe_entries = last_emit_by_key_.size();
  return out;
}

std::optional<std::string> TargetGovernor::payload_value(const common::Payload& payload, const std::string& key) {
  if (const auto it = payload.find(key); it != payload.end() && !it->second.empty()) {
    return it->second;
  }
  return std::nullopt;
}

std::string TargetGovernor::normalize_token(std::string value) { return lower_copy(std::move(value)); }

bool TargetGovernor::contains_token(const std::string& value, const std::string& token) {
  return value.find(token) != std::string::npos;
}

bool TargetGovernor::is_face_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return contains_token(normalized, "face") || contains_token(normalized, "gaze");
}

bool TargetGovernor::is_familiar_face_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return contains_token(normalized, "familiar_face") || normalized == "face_identity_detected";
}

bool TargetGovernor::is_stranger_face_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return contains_token(normalized, "stranger_face");
}

bool TargetGovernor::is_gesture_pose_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return contains_token(normalized, "gesture") || contains_token(normalized, "wave") || contains_token(normalized, "pose");
}

bool TargetGovernor::is_special_audio_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return normalized == "loud_sound_detected" || normalized == "special_audio_detected" ||
         normalized == "bark_detected" || normalized == "meow_detected" ||
         contains_token(normalized, "special_audio_") || contains_token(normalized, "bark_") ||
         contains_token(normalized, "meow_");
}

bool TargetGovernor::is_moving_object_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return normalized == "motion_detected" || normalized == "object_detected" ||
         contains_token(normalized, "moving") || contains_token(normalized, "approaching");
}

bool TargetGovernor::is_attention_probe_event(const std::string& event_type) {
  const auto normalized = normalize_token(event_type);
  return normalized == "face_attention_detected" || normalized == "person_present_detected" ||
         normalized == "gaze_sustained_detected" || contains_token(normalized, "attention");
}

common::EventPriority TargetGovernor::suggested_priority(const std::string& event_type, common::EventPriority fallback) {
  if (is_familiar_face_event(event_type)) {
    return common::EventPriority::P0;
  }
  if (is_stranger_face_event(event_type)) {
    return common::EventPriority::P1;
  }
  if (is_special_audio_event(event_type)) {
    return common::EventPriority::P0;
  }
  if (is_gesture_pose_event(event_type) || is_moving_object_event(event_type) || is_attention_probe_event(event_type)) {
    return common::EventPriority::P2;
  }
  return fallback;
}

std::optional<std::string> TargetGovernor::canonical_target_id(const common::RawEvent& event) {
  if (const auto value = payload_value(event.payload, "target_id"); value.has_value()) {
    return value;
  }
  if (const auto value = payload_value(event.payload, "track_id"); value.has_value()) {
    return value;
  }
  return std::nullopt;
}

std::optional<std::string> TargetGovernor::resolve_face_id(
    const common::RawEvent& event,
    const std::string& target_id) const {
  if (const auto value = payload_value(event.payload, "face_id"); value.has_value()) {
    return value;
  }
  if (const auto value = payload_value(event.payload, "identity_hint"); value.has_value()) {
    return value;
  }
  if (const auto value = payload_value(event.payload, "identity_target_id"); value.has_value()) {
    return value;
  }
  if (const auto it = track_face_bindings_.find(target_id); it != track_face_bindings_.end()) {
    return it->second;
  }
  return std::nullopt;
}

void TargetGovernor::maybe_bind_face_identity(const common::RawEvent& event, const std::string& target_id) {
  if (!is_face_event(event.event_type)) {
    return;
  }
  auto face_id = payload_value(event.payload, "face_id");
  if (!face_id.has_value()) {
    face_id = payload_value(event.payload, "identity_hint");
  }
  if (!face_id.has_value()) {
    face_id = payload_value(event.payload, "identity_target_id");
  }
  if (!face_id.has_value()) {
    return;
  }
  track_face_bindings_[target_id] = *face_id;
}

double TargetGovernor::cooldown_for(const common::RawEvent& event) const {
  if (is_familiar_face_event(event.event_type)) {
    return rules_.familiar_face_cooldown_s;
  }
  if (is_stranger_face_event(event.event_type)) {
    return rules_.stranger_face_cooldown_s;
  }
  if (is_gesture_pose_event(event.event_type)) {
    return rules_.gesture_pose_cooldown_s;
  }
  if (is_special_audio_event(event.event_type)) {
    return rules_.special_audio_cooldown_s;
  }
  if (is_moving_object_event(event.event_type)) {
    return rules_.moving_object_cooldown_s;
  }
  if (is_attention_probe_event(event.event_type)) {
    return rules_.attention_probe_cooldown_s;
  }
  return 0.0;
}

std::string TargetGovernor::dedupe_key_for(
    const common::RawEvent& event,
    const std::string& target_id,
    const std::optional<std::string>& face_id) const {
  const auto event_type = normalize_token(event.event_type);
  if ((is_familiar_face_event(event_type) || is_stranger_face_event(event_type)) && face_id.has_value()) {
    return event_type + "|face:" + *face_id;
  }
  return event_type + "|target:" + target_id;
}

void TargetGovernor::refresh_preempt(double now_mono_s) {
  if (special_audio_preempt_until_ <= 0.0 || now_mono_s < special_audio_preempt_until_) {
    return;
  }

  special_audio_preempt_until_ = 0.0;
  if (preempted_target_id_.has_value()) {
    active_target_id_ = preempted_target_id_;
    active_scene_type_ = preempted_scene_type_;
    active_priority_ = preempted_priority_;
    active_until_ = std::max(now_mono_s + 0.5, preempted_active_until_);
  }
  preempted_target_id_.reset();
  preempted_scene_type_.reset();
  preempted_priority_ = common::EventPriority::P3;
  preempted_active_until_ = 0.0;
}

void TargetGovernor::gc(double now_mono_s) {
  gc_counter_ += 1;
  if (gc_counter_ % 128 != 0) {
    return;
  }

  const auto stale_threshold = std::max(30.0, rules_.gc_window_s);
  for (auto it = last_emit_by_key_.begin(); it != last_emit_by_key_.end();) {
    if ((now_mono_s - it->second) > stale_threshold) {
      it = last_emit_by_key_.erase(it);
    } else {
      ++it;
    }
  }
}

}  // namespace robot_life_cpp::runtime
