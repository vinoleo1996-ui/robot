#include "robot_life_cpp/event_engine/entity_tracker.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <iomanip>
#include <optional>
#include <sstream>

namespace robot_life_cpp::event_engine {

EntityTracker::EntityTracker(double person_ttl_s, double object_ttl_s)
    : person_ttl_s_(std::max(0.1, person_ttl_s)),
      object_ttl_s_(std::max(0.1, object_ttl_s)) {}

std::vector<std::pair<std::string, common::DetectionResult>> EntityTracker::associate_batch(
    const std::vector<std::pair<std::string, common::DetectionResult>>& items,
    double now_mono_s) {
  prune(now_mono_s);
  std::vector<std::pair<std::string, common::DetectionResult>> associated{};
  associated.reserve(items.size());

  for (const auto& [pipeline_name, detection] : items) {
    auto updated_detection = detection;
    auto payload = updated_detection.payload;
    const auto modality = infer_modality(pipeline_name, updated_detection);
    const auto original_target_it = payload.find("target_id");
    const auto original_target = original_target_it == payload.end() ? "" : original_target_it->second;
    const auto identity_hint = looks_like_ephemeral_target(original_target) ? "" : original_target;
    const auto external_track_key = make_external_track_key(modality, updated_detection, payload);
    const auto allow_recent_fallback =
        !is_person_like_modality(modality) || !identity_hint.empty() || external_track_key.has_value();

    EntityTrack* track = resolve_track(
        modality,
        identity_hint,
        external_track_key,
        allow_recent_fallback,
        now_mono_s);
    if (track == nullptr) {
      const auto kind = modality == "motion" ? "object" : (modality == "audio" ? "global" : "person");
      track = &create_track(kind, identity_hint, now_mono_s);
    }

    track->last_seen_at = now_mono_s;
    track->detection_count += 1;
    track->last_detector = updated_detection.detector;
    track->last_event_type = updated_detection.event_type;
    if (!identity_hint.empty()) {
      track->identity_hint = identity_hint;
    }
    if (external_track_key.has_value()) {
      track->external_track_key = *external_track_key;
      external_track_to_internal_[*external_track_key] = track->track_id;
    }

    if (!original_target.empty()) {
      payload["identity_target_id"] = original_target;
    }
    payload["target_id"] = track->track_id;
    payload["track_id"] = track->track_id;
    payload["track_kind"] = track->track_kind;
    payload["track_detection_count"] = std::to_string(track->detection_count);
    if (!track->identity_hint.empty()) {
      payload["identity_hint"] = track->identity_hint;
    }
    updated_detection.payload = std::move(payload);
    associated.emplace_back(pipeline_name, std::move(updated_detection));
  }
  return associated;
}

EntityTrackerSnapshot EntityTracker::snapshot(double now_mono_s) {
  prune(now_mono_s);
  EntityTrackerSnapshot snap{};
  snap.active_track_count = tracks_.size();
  snap.tracks.reserve(tracks_.size());
  for (const auto& [_, track] : tracks_) {
    snap.tracks.push_back(track);
  }
  std::sort(
      snap.tracks.begin(),
      snap.tracks.end(),
      [](const EntityTrack& lhs, const EntityTrack& rhs) {
        if (lhs.track_kind != rhs.track_kind) {
          return lhs.track_kind < rhs.track_kind;
        }
        return lhs.track_id < rhs.track_id;
      });
  return snap;
}

bool EntityTracker::looks_like_ephemeral_target(const std::string& value) {
  std::string normalized = value;
  std::transform(normalized.begin(), normalized.end(), normalized.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (normalized.empty()) {
    return true;
  }
  const std::array<std::string, 6> prefixes = {
      "unknown",
      "mock_user",
      "user_",
      "track_",
      "person_track_",
      "object_track_",
  };
  return std::any_of(prefixes.begin(), prefixes.end(), [&](const std::string& prefix) {
    return normalized.rfind(prefix, 0) == 0;
  });
}

std::string EntityTracker::infer_modality(
    const std::string& pipeline_name,
    const common::DetectionResult& detection) {
  auto normalize = [](std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
  };
  const auto pipeline = normalize(pipeline_name);
  const auto detector = normalize(detection.detector);
  const auto event_type = normalize(detection.event_type);

  if (pipeline.find("face") != std::string::npos ||
      detector.find("face") != std::string::npos ||
      event_type.find("face") != std::string::npos) {
    return "face";
  }
  if (pipeline.find("gaze") != std::string::npos ||
      detector.find("gaze") != std::string::npos ||
      event_type.find("gaze") != std::string::npos) {
    return "gaze";
  }
  if (pipeline.find("gesture") != std::string::npos ||
      detector.find("gesture") != std::string::npos ||
      event_type.find("gesture") != std::string::npos) {
    return "gesture";
  }
  if (pipeline.find("motion") != std::string::npos ||
      detector.find("motion") != std::string::npos ||
      event_type.find("motion") != std::string::npos) {
    return "motion";
  }
  if (pipeline.find("audio") != std::string::npos ||
      detector.find("audio") != std::string::npos ||
      event_type.find("sound") != std::string::npos) {
    return "audio";
  }
  return pipeline.empty() ? "unknown" : pipeline;
}

bool EntityTracker::is_person_like_modality(const std::string& modality) {
  return modality == "face" || modality == "gaze" || modality == "gesture";
}

bool EntityTracker::is_object_like_modality(const std::string& modality) {
  return modality == "motion";
}

std::optional<std::string> EntityTracker::make_external_track_key(
    const std::string& modality,
    const common::DetectionResult& detection,
    const common::Payload& payload) {
  auto detector = detection.detector.empty() ? std::string{"unknown_detector"} : detection.detector;
  std::transform(detector.begin(), detector.end(), detector.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

  std::string token{};
  if (const auto track_it = payload.find("track_id"); track_it != payload.end() && !track_it->second.empty()) {
    token = track_it->second;
  } else if (const auto target_it = payload.find("target_id"); target_it != payload.end() && !target_it->second.empty()) {
    token = target_it->second;
  }
  if (token.empty()) {
    return std::nullopt;
  }
  return modality + "|" + detector + "|" + token;
}

EntityTrack* EntityTracker::resolve_track(
    const std::string& modality,
    const std::string& identity_hint,
    const std::optional<std::string>& external_track_key,
    bool allow_recent_fallback,
    double now_mono_s) {
  const bool person_like = is_person_like_modality(modality);
  const bool object_like = is_object_like_modality(modality);
  const auto ttl_s = person_like ? person_ttl_s_ : (object_like ? object_ttl_s_ : 0.5);

  if (external_track_key.has_value()) {
    if (const auto mapping_it = external_track_to_internal_.find(*external_track_key);
        mapping_it != external_track_to_internal_.end()) {
      if (const auto track_it = tracks_.find(mapping_it->second); track_it != tracks_.end()) {
        auto& mapped = track_it->second;
        if ((now_mono_s - mapped.last_seen_at) <= ttl_s &&
            ((person_like && mapped.track_kind == "person") ||
             (object_like && mapped.track_kind == "object") ||
             (!person_like && !object_like && mapped.track_kind == "global"))) {
          return &mapped;
        }
      }
    }
  }

  EntityTrack* best = nullptr;
  for (auto& [_, track] : tracks_) {
    if (person_like && track.track_kind != "person") {
      continue;
    }
    if (object_like && track.track_kind != "object") {
      continue;
    }
    if (!person_like && !object_like && track.track_kind != "global") {
      continue;
    }
    if ((now_mono_s - track.last_seen_at) > ttl_s) {
      continue;
    }
    if (!identity_hint.empty() && !track.identity_hint.empty() && track.identity_hint == identity_hint) {
      return &track;
    }
    if (best == nullptr || track.last_seen_at > best->last_seen_at) {
      best = &track;
    }
  }
  if (external_track_key.has_value()) {
    return nullptr;
  }
  if (!allow_recent_fallback) {
    return nullptr;
  }
  return best;
}

EntityTrack& EntityTracker::create_track(
    const std::string& kind,
    const std::string& identity_hint,
    double now_mono_s) {
  std::string track_id{};
  if (kind == "person") {
    std::ostringstream oss;
    oss << "person_track_" << std::setw(3) << std::setfill('0') << next_person_id_++;
    track_id = oss.str();
  } else if (kind == "object") {
    std::ostringstream oss;
    oss << "object_track_" << std::setw(3) << std::setfill('0') << next_object_id_++;
    track_id = oss.str();
  } else {
    track_id = "global_track";
  }

  EntityTrack track{};
  track.track_id = track_id;
  track.track_kind = kind;
  track.created_at = now_mono_s;
  track.last_seen_at = now_mono_s;
  track.identity_hint = identity_hint;
  return tracks_.emplace(track_id, std::move(track)).first->second;
}

void EntityTracker::prune(double now_mono_s) {
  std::vector<std::string> stale{};
  stale.reserve(tracks_.size());
  for (const auto& [track_id, track] : tracks_) {
    double ttl_s = 0.5;
    if (track.track_kind == "person") {
      ttl_s = person_ttl_s_;
    } else if (track.track_kind == "object") {
      ttl_s = object_ttl_s_;
    }
    if ((now_mono_s - track.last_seen_at) > ttl_s) {
      stale.push_back(track_id);
    }
  }
  for (const auto& track_id : stale) {
    tracks_.erase(track_id);
  }
  for (auto it = external_track_to_internal_.begin(); it != external_track_to_internal_.end();) {
    if (tracks_.find(it->second) == tracks_.end()) {
      it = external_track_to_internal_.erase(it);
    } else {
      ++it;
    }
  }
}

}  // namespace robot_life_cpp::event_engine
