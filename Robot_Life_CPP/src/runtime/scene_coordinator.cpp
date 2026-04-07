#include "robot_life_cpp/runtime/scene_coordinator.hpp"

#include <algorithm>
#include <cctype>
#include <unordered_map>

namespace robot_life_cpp::runtime {

namespace {

bool has_token(const std::string& value, const std::string& token) {
  return value.find(token) != std::string::npos;
}

bool is_special_audio_trigger(const std::string& normalized_event_type) {
  return normalized_event_type == "loud_sound_detected" || normalized_event_type == "special_audio_detected" ||
         normalized_event_type == "bark_detected" || normalized_event_type == "meow_detected" ||
         has_token(normalized_event_type, "special_audio_") || has_token(normalized_event_type, "bark_") ||
         has_token(normalized_event_type, "meow_") || has_token(normalized_event_type, "loud_sound");
}

std::string to_lower_copy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
  return value;
}

std::string payload_lookup_lower(
    const common::Payload& payload,
    const std::string& key) {
  if (const auto it = payload.find(key); it != payload.end()) {
    return to_lower_copy(it->second);
  }
  return {};
}

}  // namespace

SceneCoordinator::SceneCoordinator(SceneCoordinatorRules rules) : rules_(std::move(rules)) {
  rules_.scene_ttl_s = std::max(0.3, rules_.scene_ttl_s);
  rules_.min_confidence = std::clamp(rules_.min_confidence, 0.0, 1.0);
}

void SceneCoordinator::reconfigure(SceneCoordinatorRules rules) {
  rules.scene_ttl_s = std::max(0.3, rules.scene_ttl_s);
  rules.min_confidence = std::clamp(rules.min_confidence, 0.0, 1.0);
  rules_ = std::move(rules);
}

std::vector<common::SceneCandidate> SceneCoordinator::derive(
    const std::vector<common::StableEvent>& stable_events,
    double now_mono_s) const {
  std::unordered_map<std::string, common::SceneCandidate> dedup{};

  for (const auto& event : stable_events) {
    const auto scene_type = map_event_to_scene(event.event_type, event.payload);
    if (!scene_type.has_value()) {
      continue;
    }

    const auto confidence = confidence_of(event);
    if (confidence < rules_.min_confidence) {
      continue;
    }

    common::SceneCandidate candidate{};
    candidate.scene_id = common::new_id();
    candidate.trace_id = event.trace_id;
    candidate.scene_type = *scene_type;
    candidate.based_on_events = {event.stable_event_id};
    candidate.score_hint = std::clamp(confidence + (1.0 - static_cast<double>(common::priority_rank(event.priority))) * 0.15, 0.0, 10.0);
    candidate.valid_until_monotonic = std::max(event.valid_until_monotonic, now_mono_s + rules_.scene_ttl_s);
    candidate.target_id = resolve_target_id(event);
    candidate.payload = event.payload;
    candidate.payload["source_event_type"] = event.event_type;
    candidate.payload["scene_origin"] = "coordinator_hint";
    candidate.payload["scene_role"] = "metadata";
    if (const auto behavior = map_scene_to_behavior(*scene_type); behavior.has_value()) {
      candidate.payload["scene_behavior_hint"] = *behavior;
    }

    const auto dedupe_key = candidate.scene_type + ":" + candidate.target_id.value_or("__any__");
    if (const auto it = dedup.find(dedupe_key); it != dedup.end()) {
      if (candidate.score_hint > it->second.score_hint) {
        dedup[dedupe_key] = std::move(candidate);
      } else {
        it->second.based_on_events.push_back(event.stable_event_id);
      }
      continue;
    }
    dedup[dedupe_key] = std::move(candidate);
  }

  std::vector<common::SceneCandidate> out{};
  out.reserve(dedup.size());
  for (auto& [_, scene] : dedup) {
    out.push_back(std::move(scene));
  }
  std::sort(out.begin(), out.end(), [](const common::SceneCandidate& lhs, const common::SceneCandidate& rhs) {
    return lhs.score_hint > rhs.score_hint;
  });
  return out;
}

std::optional<std::string> SceneCoordinator::map_event_to_scene(
    const std::string& event_type,
    const common::Payload& payload) {
  const auto normalized = to_lower_copy(event_type);
  if (normalized == "familiar_face_detected") {
    return "greeting_familiar_scene";
  }
  if (normalized == "stranger_face_detected") {
    return "greeting_stranger_scene";
  }
  if (normalized == "face_identity_detected") {
    const auto identity_state = payload_lookup_lower(payload, "identity_state");
    if (identity_state == "familiar" || identity_state == "known" || identity_state == "owner") {
      return "greeting_familiar_scene";
    }
    if (identity_state == "stranger" || identity_state == "unknown") {
      return "greeting_stranger_scene";
    }
    return "attention_detection_scene";
  }
  if (is_special_audio_trigger(normalized)) {
    return "special_audio_attention_scene";
  }
  if (normalized == "pose_detected" || normalized == "gesture_detected" || normalized == "wave_detected") {
    return "gesture_pose_response_scene";
  }
  if (normalized == "motion_detected" || normalized == "object_detected" || normalized == "approaching_detected") {
    return "moving_object_attention_scene";
  }
  if (normalized == "face_attention_detected" || normalized == "gaze_sustained_detected" ||
      normalized == "person_present_detected") {
    return "attention_detection_scene";
  }

  if (has_token(normalized, "gesture") || has_token(normalized, "wave")) {
    return "gesture_pose_response_scene";
  }
  if (is_special_audio_trigger(normalized)) {
    return "special_audio_attention_scene";
  }
  if (has_token(normalized, "motion") || has_token(normalized, "object")) {
    return "moving_object_attention_scene";
  }
  if (has_token(normalized, "gaze") || has_token(normalized, "attention")) {
    return "attention_detection_scene";
  }
  if (has_token(normalized, "face")) {
    return "greeting_stranger_scene";
  }
  return std::nullopt;
}

std::optional<std::string> SceneCoordinator::map_scene_to_behavior(const std::string& scene_type) {
  if (scene_type == "greeting_familiar_scene" || scene_type == "greeting_stranger_scene") {
    return "perform_greeting";
  }
  if (scene_type == "gesture_pose_response_scene") {
    return "perform_gesture_response";
  }
  if (scene_type == "special_audio_attention_scene" || scene_type == "attention_detection_scene") {
    return "perform_attention";
  }
  if (scene_type == "moving_object_attention_scene") {
    return "perform_tracking";
  }
  return std::nullopt;
}

std::optional<std::string> SceneCoordinator::resolve_target_id(const common::StableEvent& event) {
  if (const auto it = event.payload.find("target_id"); it != event.payload.end() && !it->second.empty()) {
    return it->second;
  }
  if (const auto it = event.payload.find("track_id"); it != event.payload.end() && !it->second.empty()) {
    return it->second;
  }
  return std::nullopt;
}

double SceneCoordinator::confidence_of(const common::StableEvent& event) {
  if (const auto it = event.payload.find("confidence"); it != event.payload.end()) {
    try {
      return std::clamp(std::stod(it->second), 0.0, 1.0);
    } catch (...) {
    }
  }
  if (const auto it = event.payload.find("event_confidence"); it != event.payload.end()) {
    try {
      return std::clamp(std::stod(it->second), 0.0, 1.0);
    } catch (...) {
    }
  }
  return 0.7;
}

}  // namespace robot_life_cpp::runtime
