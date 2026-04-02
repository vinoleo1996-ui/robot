#include "robot_life_cpp/event_engine/arbitration_runtime.hpp"

#include <algorithm>

namespace robot_life_cpp::event_engine {

ArbitrationRuntime::ArbitrationRuntime()
    : ArbitrationRuntime(Arbitrator{}, DecisionQueue{}) {}

ArbitrationRuntime::ArbitrationRuntime(
    Arbitrator arbitrator,
    DecisionQueue queue,
    int batch_window_ms,
    std::size_t p1_queue_limit,
    std::size_t p2_queue_limit,
    int starvation_after_ms)
    : arbitrator_(std::move(arbitrator)),
      queue_(std::move(queue)),
      batch_window_ms_(std::max(1, batch_window_ms)),
      p1_queue_limit_(std::max<std::size_t>(1, p1_queue_limit)),
      p2_queue_limit_(std::max<std::size_t>(1, p2_queue_limit)),
      starvation_after_ms_(std::max(0, starvation_after_ms)) {}

std::optional<common::ArbitrationResult> ArbitrationRuntime::submit(
    const common::SceneCandidate& scene,
    std::optional<common::EventPriority> current_priority,
    std::optional<int> batch_window_ms,
    double now_mono_s) {
  auto outcome = submit_scene(scene, current_priority, batch_window_ms, now_mono_s);
  if (!outcome.executed) {
    return std::nullopt;
  }
  return outcome.decision;
}

std::vector<ArbitrationBatchOutcome> ArbitrationRuntime::submit_batch(
    const std::vector<common::SceneCandidate>& scenes,
    std::optional<common::EventPriority> current_priority,
    std::optional<int> batch_window_ms,
    double now_mono_s) {
  if (scenes.empty()) {
    return {};
  }

  std::vector<ArbitrationBatchOutcome> outcomes{};
  outcomes.reserve(scenes.size());
  auto simulated_priority = current_priority.has_value() ? current_priority : active_priority_;
  for (const auto& scene : scenes) {
    auto outcome = submit_scene(scene, simulated_priority, batch_window_ms, now_mono_s);
    outcomes.push_back(outcome);
    if (outcome.executed) {
      simulated_priority = outcome.decision.priority;
    }
  }
  return outcomes;
}

std::optional<common::ArbitrationResult> ArbitrationRuntime::complete_active(double now_mono_s) {
  active_priority_.reset();
  auto promoted = queue_.pop_starved_oldest(
      starvation_after_ms_,
      {common::EventPriority::P2, common::EventPriority::P3},
      now_mono_s);
  if (!promoted.has_value()) {
    promoted = queue_.pop_next(now_mono_s);
  }

  active_decision_key_.reset();
  if (!promoted.has_value()) {
    return std::nullopt;
  }

  common::ArbitrationResult next = *promoted;
  next.mode = common::DecisionMode::Execute;
  next.reason = "dequeued: " + next.reason;
  active_priority_ = next.priority;
  const auto key_it = decision_keys_.find(next.decision_id);
  if (key_it != decision_keys_.end()) {
    active_decision_key_ = key_it->second;
  }
  last_decision_ = next;
  record_outcome("dequeued");
  return next;
}

void ArbitrationRuntime::clear() {
  active_priority_.reset();
  active_decision_key_.reset();
  last_decision_.reset();
  last_outcome_ = "idle";
  decision_keys_.clear();
  recent_p1_keys_.clear();
  recent_p2_keys_.clear();
  queue_.clear();
}

std::size_t ArbitrationRuntime::pending(double now_mono_s) { return queue_.size(now_mono_s); }

std::optional<common::EventPriority> ArbitrationRuntime::active_priority() const { return active_priority_; }

const std::string& ArbitrationRuntime::last_outcome() const { return last_outcome_; }

std::optional<common::ArbitrationResult> ArbitrationRuntime::last_decision() const { return last_decision_; }

std::unordered_map<std::string, int> ArbitrationRuntime::outcome_counts() const { return outcome_counts_; }

std::string ArbitrationRuntime::decision_key(
    const common::SceneCandidate& scene,
    const common::ArbitrationResult& decision) {
  if (decision.priority != common::EventPriority::P1 && decision.priority != common::EventPriority::P2) {
    return {};
  }
  const auto target = scene.target_id.value_or("any");
  return scene.scene_type + ":" + target + ":" + decision.target_behavior;
}

std::string ArbitrationRuntime::target_from_key(const std::string& key) {
  if (key.empty()) {
    return "any";
  }
  const auto first = key.find(':');
  if (first == std::string::npos) {
    return "any";
  }
  const auto second = key.find(':', first + 1);
  if (second == std::string::npos) {
    return key.substr(first + 1);
  }
  return key.substr(first + 1, second - first - 1);
}

int ArbitrationRuntime::queue_timeout_ms(common::EventPriority priority) {
  switch (priority) {
    case common::EventPriority::P0:
      return 500;
    case common::EventPriority::P1:
      return 5000;
    case common::EventPriority::P2:
      return 10000;
    case common::EventPriority::P3:
      return 15000;
  }
  return 5000;
}

ArbitrationBatchOutcome ArbitrationRuntime::submit_scene(
    const common::SceneCandidate& scene,
    std::optional<common::EventPriority> current_priority,
    std::optional<int> batch_window_ms,
    double now_mono_s) {
  ArbitrationBatchOutcome outcome{};
  outcome.scene = scene;

  const auto decision_opt = arbitrator_.decide({scene}, now_mono_s);
  if (!decision_opt.has_value()) {
    common::ArbitrationResult none{};
    none.decision_id = common::new_id();
    none.trace_id = scene.trace_id;
    none.target_behavior = "idle_scan";
    none.priority = common::EventPriority::P3;
    none.mode = common::DecisionMode::Drop;
    none.reason = "no_decision";
    outcome.decision = none;
    outcome.outcome = "idle";
    outcome.executed = false;
    record_outcome("idle");
    return outcome;
  }

  common::ArbitrationResult decision = *decision_opt;
  const auto active = current_priority.has_value() ? current_priority : active_priority_;
  if (active.has_value()) {
    const auto incoming_rank = common::priority_rank(decision.priority);
    const auto active_rank = common::priority_rank(*active);
    if (incoming_rank > active_rank) {
      decision.mode = common::DecisionMode::Queue;
      decision.reason += "|policy=queue_lower_than_active";
    } else if (incoming_rank == active_rank && decision.priority == common::EventPriority::P3) {
      decision.mode = common::DecisionMode::Drop;
      decision.reason += "|policy=drop_equal_p3";
    }
  }

  last_decision_ = decision;
  if (decision.mode == common::DecisionMode::Queue || decision.mode == common::DecisionMode::Drop) {
    if (should_enqueue_with_replace(decision)) {
      const auto state = enqueue_with_replace(scene, decision, batch_window_ms, now_mono_s);
      outcome.decision = decision;
      outcome.outcome = state;
      outcome.executed = false;
      record_outcome(state);
      return outcome;
    }

    if (decision.mode == common::DecisionMode::Queue ||
        (decision.mode == common::DecisionMode::Drop &&
         (decision.priority == common::EventPriority::P2 || decision.priority == common::EventPriority::P3))) {
      const auto queued = queue_.enqueue(
          decision,
          queue_timeout_ms(decision.priority),
          std::nullopt,
          0,
          now_mono_s);
      if (queued.has_value()) {
        outcome.decision = decision;
        outcome.outcome = "queued";
        outcome.executed = false;
        record_outcome("queued");
        return outcome;
      }
    }

    const std::string terminal = decision.mode == common::DecisionMode::Drop ? "dropped" : "debounced";
    outcome.decision = decision;
    outcome.outcome = terminal;
    outcome.executed = false;
    record_outcome(terminal);
    return outcome;
  }

  active_priority_ = decision.priority;
  const auto key = decision_key(scene, decision);
  active_decision_key_ = key.empty() ? std::nullopt : std::optional<std::string>(key);
  remember_decision_key(decision, active_decision_key_);
  if ((decision.priority == common::EventPriority::P1 || decision.priority == common::EventPriority::P2) &&
      active_decision_key_.has_value()) {
    auto& recent = recent_key_store(decision.priority);
    recent[*active_decision_key_] = now_mono_s;
    prune_recent_keys(decision.priority, now_mono_s, batch_window_ms);
  }
  outcome.decision = decision;
  outcome.outcome = "executed";
  outcome.executed = true;
  record_outcome("executed");
  return outcome;
}

std::string ArbitrationRuntime::enqueue_with_replace(
    const common::SceneCandidate& scene,
    const common::ArbitrationResult& decision,
    std::optional<int> batch_window_ms,
    double now_mono_s) {
  const auto key = decision_key(scene, decision);
  if (key.empty()) {
    return "dropped";
  }

  auto& recent = recent_key_store(decision.priority);
  prune_recent_keys(decision.priority, now_mono_s, batch_window_ms);

  const auto limit = queue_limit(decision.priority);
  if (queue_.count(decision.priority, now_mono_s) >= limit && !queue_.has_replace_key(key, now_mono_s)) {
    evict_for_fairness(decision.priority, key);
  }

  const int debounce_ms = resolved_batch_window_ms(batch_window_ms, decision.priority);
  const auto recent_it = recent.find(key);
  if (recent_it != recent.end() && (now_mono_s - recent_it->second) < (static_cast<double>(debounce_ms) / 1000.0)) {
    if (!queue_.has_replace_key(key, now_mono_s)) {
      remember_decision_key(decision, key);
      recent[key] = now_mono_s;
      return "debounced";
    }
  }

  auto queued = queue_.enqueue(
      decision,
      queue_timeout_ms(decision.priority),
      key,
      debounce_ms,
      now_mono_s);
  if (!queued.has_value()) {
    recent[key] = now_mono_s;
    remember_decision_key(decision, key);
    return "debounced";
  }

  recent[key] = now_mono_s;
  remember_decision_key(decision, key);
  return "queued";
}

bool ArbitrationRuntime::should_enqueue_with_replace(const common::ArbitrationResult& decision) const {
  return (decision.mode == common::DecisionMode::Queue || decision.mode == common::DecisionMode::Drop) &&
         (decision.priority == common::EventPriority::P1 || decision.priority == common::EventPriority::P2);
}

int ArbitrationRuntime::resolved_batch_window_ms(
    std::optional<int> batch_window_ms,
    common::EventPriority priority) const {
  const auto base = batch_window_ms.has_value() ? std::max(1, *batch_window_ms) : batch_window_ms_;
  if (priority == common::EventPriority::P2) {
    return std::max(base * 2, 80);
  }
  return base;
}

std::size_t ArbitrationRuntime::queue_limit(common::EventPriority priority) const {
  if (priority == common::EventPriority::P1) {
    return p1_queue_limit_;
  }
  if (priority == common::EventPriority::P2) {
    return p2_queue_limit_;
  }
  return std::max(p1_queue_limit_, p2_queue_limit_);
}

void ArbitrationRuntime::evict_for_fairness(
    common::EventPriority priority,
    const std::optional<std::string>& incoming_key) {
  if (!incoming_key.has_value()) {
    queue_.drop_oldest(priority);
    return;
  }

  const auto queued_items = queue_.items(priority);
  if (queued_items.empty()) {
    return;
  }

  const auto incoming_target = target_from_key(*incoming_key);
  std::unordered_map<std::string, int> counts{};
  for (const auto& item : queued_items) {
    const auto key = queue_.replace_key_for(item.queue_id);
    if (!key.has_value()) {
      continue;
    }
    counts[target_from_key(*key)] += 1;
  }

  std::string preferred_target = incoming_target;
  if (!counts.contains(preferred_target) || counts[preferred_target] <= 0) {
    int max_count = -1;
    for (const auto& [target, count] : counts) {
      if (count > max_count) {
        max_count = count;
        preferred_target = target;
      }
    }
  }

  for (const auto& item : queued_items) {
    const auto key = queue_.replace_key_for(item.queue_id);
    if (!key.has_value()) {
      continue;
    }
    if (target_from_key(*key) == preferred_target) {
      queue_.drop_queue_id(item.queue_id);
      return;
    }
  }
  queue_.drop_oldest(priority);
}

void ArbitrationRuntime::remember_decision_key(
    const common::ArbitrationResult& decision,
    const std::optional<std::string>& key) {
  if (key.has_value() && !key->empty()) {
    decision_keys_[decision.decision_id] = *key;
  }
}

void ArbitrationRuntime::prune_recent_keys(
    common::EventPriority priority,
    double now_mono_s,
    std::optional<int> batch_window_ms) {
  auto& store = recent_key_store(priority);
  const auto ttl_s = static_cast<double>(resolved_batch_window_ms(batch_window_ms, priority)) / 1000.0;
  std::vector<std::string> stale{};
  stale.reserve(store.size());
  for (const auto& [key, seen_at] : store) {
    if ((now_mono_s - seen_at) > ttl_s) {
      stale.push_back(key);
    }
  }
  for (const auto& key : stale) {
    store.erase(key);
  }
}

std::unordered_map<std::string, double>& ArbitrationRuntime::recent_key_store(common::EventPriority priority) {
  if (priority == common::EventPriority::P2) {
    return recent_p2_keys_;
  }
  return recent_p1_keys_;
}

void ArbitrationRuntime::record_outcome(const std::string& outcome) {
  last_outcome_ = outcome;
  const auto it = outcome_counts_.find(outcome);
  if (it != outcome_counts_.end()) {
    it->second += 1;
  }
}

}  // namespace robot_life_cpp::event_engine
