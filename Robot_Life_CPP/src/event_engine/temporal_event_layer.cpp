#include "robot_life_cpp/event_engine/temporal_event_layer.hpp"

#include <algorithm>

namespace robot_life_cpp::event_engine {

TemporalEventLayer::TemporalEventLayer(double gaze_hold_ttl_s, double attention_memory_ttl_s)
    : gaze_hold_ttl_s_(std::max(0.5, gaze_hold_ttl_s)),
      attention_memory_ttl_s_(std::max(0.5, attention_memory_ttl_s)) {}

std::vector<common::StableEvent> TemporalEventLayer::process(
    const common::StableEvent& stable_event,
    double now_mono_s) {
  prune(now_mono_s);
  std::vector<common::StableEvent> emitted{};
  emitted.push_back(stable_event);

  const auto target_id = target_id_from_payload(stable_event.payload);
  if ((stable_event.event_type == "familiar_face_detected" ||
       stable_event.event_type == "stranger_face_detected") &&
      !target_id.empty()) {
    active_attention_targets_[target_id] = now_mono_s;
  }

  if (stable_event.event_type == "gaze_sustained_detected" && !target_id.empty()) {
    std::string derived = "gaze_hold_start_detected";
    if (active_gaze_targets_.contains(target_id)) {
      derived = "gaze_hold_active_detected";
    }
    active_gaze_targets_[target_id] = now_mono_s;
    active_attention_targets_[target_id] = now_mono_s;
    emitted.push_back(derive_event(stable_event, derived, now_mono_s));
  } else if (stable_event.event_type == "gaze_away_detected" && !target_id.empty()) {
    if (active_gaze_targets_.contains(target_id)) {
      active_gaze_targets_.erase(target_id);
      emitted.push_back(derive_event(stable_event, "gaze_hold_end_detected", now_mono_s));
      emitted.push_back(derive_event(stable_event, "attention_lost_detected", now_mono_s));
    }
  } else if (stable_event.event_type == "gesture_detected") {
    const auto gesture_it = stable_event.payload.find("gesture_name");
    const auto raw_it = stable_event.payload.find("raw_event_type");
    const auto gesture = gesture_it == stable_event.payload.end() ? "" : gesture_it->second;
    const auto raw = raw_it == stable_event.payload.end() ? "" : raw_it->second;
    if (gesture == "open_palm" || gesture == "waving" ||
        raw == "gesture_open_palm" || raw == "gesture_waving" ||
        raw.find("wave") != std::string::npos) {
      emitted.push_back(derive_event(stable_event, "wave_detected", now_mono_s));
    }
  }

  return emitted;
}

TemporalLayerSnapshot TemporalEventLayer::snapshot(double now_mono_s) {
  prune(now_mono_s);
  TemporalLayerSnapshot snap{};
  snap.active_gaze_targets.reserve(active_gaze_targets_.size());
  snap.active_attention_targets.reserve(active_attention_targets_.size());
  for (const auto& [target, _] : active_gaze_targets_) {
    snap.active_gaze_targets.push_back(target);
  }
  for (const auto& [target, _] : active_attention_targets_) {
    snap.active_attention_targets.push_back(target);
  }
  std::sort(snap.active_gaze_targets.begin(), snap.active_gaze_targets.end());
  std::sort(snap.active_attention_targets.begin(), snap.active_attention_targets.end());
  return snap;
}

std::string TemporalEventLayer::target_id_from_payload(const common::Payload& payload) {
  const auto it = payload.find("target_id");
  return it == payload.end() ? "" : it->second;
}

common::StableEvent TemporalEventLayer::derive_event(
    const common::StableEvent& base,
    const std::string& event_type,
    double now_mono_s) {
  common::StableEvent derived = base;
  derived.stable_event_id = common::new_id();
  derived.event_type = event_type;
  derived.valid_until_monotonic = std::max(base.valid_until_monotonic, now_mono_s + 0.8);
  derived.stabilized_by.push_back("temporal_event_layer");
  derived.payload["derived_from_event_type"] = base.event_type;
  derived.payload["derived_temporal_event"] = event_type;
  return derived;
}

void TemporalEventLayer::prune(double now_mono_s) {
  for (auto it = active_gaze_targets_.begin(); it != active_gaze_targets_.end();) {
    if ((now_mono_s - it->second) > gaze_hold_ttl_s_) {
      it = active_gaze_targets_.erase(it);
    } else {
      ++it;
    }
  }

  for (auto it = active_attention_targets_.begin(); it != active_attention_targets_.end();) {
    if ((now_mono_s - it->second) > attention_memory_ttl_s_) {
      it = active_attention_targets_.erase(it);
    } else {
      ++it;
    }
  }
}

}  // namespace robot_life_cpp::event_engine
