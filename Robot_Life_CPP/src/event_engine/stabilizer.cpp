#include "robot_life_cpp/event_engine/stabilizer.hpp"

#include <algorithm>
#include <sstream>
#include <vector>

namespace robot_life_cpp::event_engine {

EventStabilizer::EventStabilizer(StabilizerRules rules) : rules_(rules) {
  rules_.debounce_count = std::max(1, rules_.debounce_count);
  rules_.debounce_window_s = std::max(0.0, rules_.debounce_window_s);
  rules_.cooldown_s = std::max(0.0, rules_.cooldown_s);
  rules_.dedup_window_s = std::max(0.0, rules_.dedup_window_s);
  rules_.default_ttl_ms = std::max(1, rules_.default_ttl_ms);
}

std::optional<common::StableEvent> EventStabilizer::process(
    const common::RawEvent& raw_event, double now) {
  gc(now);
  const int ttl_ms = raw_event.ttl_ms > 0 ? raw_event.ttl_ms : rules_.default_ttl_ms;
  if (now > raw_event.timestamp_monotonic + (static_cast<double>(ttl_ms) / 1000.0)) {
    return std::nullopt;
  }

  if (!check_debounce(raw_event.cooldown_key, now)) {
    return std::nullopt;
  }
  if (!check_hysteresis(raw_event.cooldown_key, raw_event.confidence, now)) {
    return std::nullopt;
  }
  if (!check_dedup(raw_event, now)) {
    return std::nullopt;
  }
  if (!check_cooldown(raw_event.cooldown_key, now)) {
    return std::nullopt;
  }

  cooldown_state_[raw_event.cooldown_key] = now;

  common::StableEvent stable{};
  stable.stable_event_id = common::new_id();
  stable.base_event_id = raw_event.event_id;
  stable.trace_id = raw_event.trace_id;
  stable.event_type = raw_event.event_type;
  stable.priority = raw_event.priority;
  stable.valid_until_monotonic = now + (static_cast<double>(ttl_ms) / 1000.0);
  stable.stabilized_by = {"debounce", "hysteresis", "dedup", "cooldown"};
  stable.payload = raw_event.payload;
  return stable;
}

void EventStabilizer::reset() {
  debounce_state_.clear();
  hysteresis_state_.clear();
  cooldown_state_.clear();
  dedup_state_.clear();
}

void EventStabilizer::reset_for_key(const std::string& cooldown_key) {
  debounce_state_.erase(cooldown_key);
  hysteresis_state_.erase(cooldown_key);
  cooldown_state_.erase(cooldown_key);
}

bool EventStabilizer::check_debounce(const std::string& key, double now) {
  if (rules_.debounce_count <= 1) {
    return true;
  }
  auto it = debounce_state_.find(key);
  if (it == debounce_state_.end()) {
    debounce_state_[key] = DebounceState{1, now};
    return false;
  }
  auto& state = it->second;
  if (rules_.debounce_window_s <= 0.0 || (now - state.first_seen_at) <= rules_.debounce_window_s) {
    state.count += 1;
    if (state.count >= rules_.debounce_count) {
      debounce_state_.erase(it);
      return true;
    }
    return false;
  }
  state = DebounceState{1, now};
  return false;
}

bool EventStabilizer::check_hysteresis(const std::string& key, double confidence, double now) {
  const double enter_threshold =
      std::max(rules_.hysteresis_threshold, rules_.hysteresis_transition_high);
  const double exit_threshold =
      std::min(rules_.hysteresis_threshold, rules_.hysteresis_transition_low);

  auto it = hysteresis_state_.find(key);
  if (it == hysteresis_state_.end()) {
    HysteresisState init{};
    init.active = confidence >= enter_threshold;
    init.last_confidence = confidence;
    init.last_seen_at = now;
    hysteresis_state_[key] = init;
    return init.active;
  }

  auto& state = it->second;
  state.last_seen_at = now;
  state.last_confidence = confidence;
  if (!state.active) {
    if (confidence >= enter_threshold) {
      state.active = true;
      return true;
    }
    return false;
  }
  if (confidence < exit_threshold) {
    state.active = false;
    return false;
  }
  return true;
}

bool EventStabilizer::check_dedup(const common::RawEvent& raw_event, double now) {
  if (rules_.dedup_window_s <= 0.0) {
    return true;
  }
  const double expire_before = now - rules_.dedup_window_s;
  for (auto it = dedup_state_.begin(); it != dedup_state_.end();) {
    if (it->second < expire_before) {
      it = dedup_state_.erase(it);
    } else {
      ++it;
    }
  }

  const auto signature = dedup_signature(raw_event);
  if (dedup_state_.contains(signature)) {
    return false;
  }
  dedup_state_[signature] = now;
  return true;
}

bool EventStabilizer::check_cooldown(const std::string& key, double now) {
  if (rules_.cooldown_s <= 0.0) {
    return true;
  }
  auto it = cooldown_state_.find(key);
  if (it == cooldown_state_.end()) {
    return true;
  }
  return (now - it->second) >= rules_.cooldown_s;
}

std::string EventStabilizer::dedup_signature(const common::RawEvent& raw_event) const {
  std::vector<std::pair<std::string, std::string>> kv;
  kv.reserve(raw_event.payload.size());
  for (const auto& item : raw_event.payload) {
    kv.push_back(item);
  }
  std::sort(kv.begin(), kv.end());

  std::ostringstream oss;
  oss << raw_event.cooldown_key << '|';
  for (const auto& [k, v] : kv) {
    oss << k << '=' << v << ';';
  }
  return oss.str();
}

void EventStabilizer::gc(double now) {
  gc_calls_ += 1;
  if (gc_calls_ % 100 != 0) {
    return;
  }

  const double debounce_expire = now - std::max(1.0, rules_.debounce_window_s * 2.0);
  for (auto it = debounce_state_.begin(); it != debounce_state_.end();) {
    if (it->second.first_seen_at < debounce_expire) {
      it = debounce_state_.erase(it);
    } else {
      ++it;
    }
  }

  const double hysteresis_expire = now - std::max(10.0, rules_.cooldown_s * 5.0);
  for (auto it = hysteresis_state_.begin(); it != hysteresis_state_.end();) {
    if (it->second.last_seen_at < hysteresis_expire) {
      it = hysteresis_state_.erase(it);
    } else {
      ++it;
    }
  }

  const double cooldown_expire = now - std::max(10.0, rules_.cooldown_s * 5.0);
  for (auto it = cooldown_state_.begin(); it != cooldown_state_.end();) {
    if (it->second < cooldown_expire) {
      it = cooldown_state_.erase(it);
    } else {
      ++it;
    }
  }
}

}  // namespace robot_life_cpp::event_engine
