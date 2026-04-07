#include "robot_life_cpp/event_engine/scene_aggregator.hpp"

#include <algorithm>

namespace robot_life_cpp::event_engine {

namespace {
bool contains_token(const std::string& value, const std::string& token) {
  return value.find(token) != std::string::npos;
}

std::optional<std::string> payload_value(
    const common::Payload& payload,
    const std::string& key) {
  if (const auto it = payload.find(key); it != payload.end() && !it->second.empty()) {
    return it->second;
  }
  return std::nullopt;
}
}  // namespace

SceneAggregator::SceneAggregator(SceneAggregatorRules rules) : rules_(std::move(rules)) {
  rules_.scene_ttl_s = std::max(0.3, rules_.scene_ttl_s);
  rules_.score_decay_s = std::max(0.3, rules_.score_decay_s);
}

std::vector<common::SceneCandidate> SceneAggregator::update(
    const std::vector<common::StableEvent>& stable_events, double now_mono_s) {
  gc(now_mono_s);

  for (const auto& event : stable_events) {
    const auto scene_type = classify_scene(event.event_type);
    const auto target_id = resolve_target_id(event);
    const auto identity_key = resolve_identity_key(event);
    auto& state = states_[state_key(scene_type, identity_key)];
    if (state.last_update > 0.0) {
      const auto age = std::max(0.0, now_mono_s - state.last_update);
      const auto decay = std::clamp(1.0 - age / rules_.score_decay_s, 0.0, 1.0);
      state.score *= decay;
    }

    state.scene_type = scene_type;
    state.target_id = target_id;
    state.identity_key = identity_key;
    state.score += event_score_hint(event);
    state.last_update = now_mono_s;
    state.trace_id = event.trace_id;
    state.payload = event.payload;
    state.event_ids.push_back(event.stable_event_id);
    if (state.event_ids.size() > 8) {
      state.event_ids.erase(state.event_ids.begin(),
                            state.event_ids.begin() +
                                static_cast<std::ptrdiff_t>(state.event_ids.size() - 8));
    }
  }

  std::vector<common::SceneCandidate> result{};
  result.reserve(states_.size());
  for (const auto& [_, state] : states_) {
    if ((now_mono_s - state.last_update) > rules_.scene_ttl_s) {
      continue;
    }

    common::SceneCandidate candidate{};
    candidate.scene_id = common::new_id();
    candidate.trace_id = state.trace_id;
    candidate.scene_type = state.scene_type;
    candidate.based_on_events = state.event_ids;
    candidate.target_id = state.target_id;
    candidate.payload = state.payload;
    if (!state.identity_key.empty()) {
      candidate.payload["identity_binding_key"] = state.identity_key;
    }
    const auto bias_it = rules_.scene_bias.find(state.scene_type);
    const double bias = bias_it == rules_.scene_bias.end() ? 1.0 : bias_it->second;
    candidate.score_hint = std::clamp(state.score * bias, 0.0, 10.0);
    candidate.valid_until_monotonic = state.last_update + rules_.scene_ttl_s;
    result.push_back(std::move(candidate));
  }

  std::sort(result.begin(), result.end(),
            [](const common::SceneCandidate& a, const common::SceneCandidate& b) {
              return a.score_hint > b.score_hint;
            });
  return result;
}

void SceneAggregator::reset() { states_.clear(); }

std::optional<std::string> SceneAggregator::resolve_target_id(const common::StableEvent& event) {
  if (const auto value = payload_value(event.payload, "target_id"); value.has_value()) {
    return value;
  }
  if (const auto value = payload_value(event.payload, "track_id"); value.has_value()) {
    return value;
  }
  return std::nullopt;
}

std::string SceneAggregator::resolve_identity_key(const common::StableEvent& event) {
  for (const auto& key : {"face_id", "identity_target_id", "identity_hint", "target_id", "track_id"}) {
    if (const auto value = payload_value(event.payload, key); value.has_value()) {
      return *value;
    }
  }
  return "__any__";
}

std::string SceneAggregator::state_key(const std::string& scene_type, const std::string& identity_key) {
  return scene_type + ":" + identity_key;
}

std::string SceneAggregator::classify_scene(const std::string& event_type) const {
  if (const auto exact_it = rules_.taxonomy.event_scene_exact.find(event_type);
      exact_it != rules_.taxonomy.event_scene_exact.end()) {
    return exact_it->second;
  }
  std::string matched_scene = rules_.taxonomy.default_scene;
  std::size_t best_match_len = 0;
  for (const auto& [token, scene] : rules_.taxonomy.event_scene_token) {
    if (token.empty() || !contains_token(event_type, token)) {
      continue;
    }
    if (token.size() > best_match_len) {
      best_match_len = token.size();
      matched_scene = scene;
    }
  }
  return matched_scene;
}

double SceneAggregator::event_score_hint(const common::StableEvent& event) {
  auto it = event.payload.find("confidence");
  if (it == event.payload.end()) {
    return 0.6;
  }
  try {
    return std::clamp(std::stod(it->second), 0.0, 1.0);
  } catch (...) {
    return 0.6;
  }
}

void SceneAggregator::gc(double now_mono_s) {
  gc_calls_ += 1;
  if (gc_calls_ % 100 != 0) {
    return;
  }
  for (auto it = states_.begin(); it != states_.end();) {
    if ((now_mono_s - it->second.last_update) > (rules_.scene_ttl_s * 2.0)) {
      it = states_.erase(it);
    } else {
      ++it;
    }
  }
}

}  // namespace robot_life_cpp::event_engine
