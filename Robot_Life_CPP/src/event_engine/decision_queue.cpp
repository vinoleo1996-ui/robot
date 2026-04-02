#include "robot_life_cpp/event_engine/decision_queue.hpp"

#include <algorithm>

namespace robot_life_cpp::event_engine {

DecisionQueue::DecisionQueue(int default_timeout_ms, std::size_t max_size)
    : default_timeout_ms_(std::max(1, default_timeout_ms)),
      max_size_(std::max<std::size_t>(1, max_size)) {}

std::optional<DecisionQueueItem> DecisionQueue::enqueue(
    common::ArbitrationResult decision,
    std::optional<int> timeout_ms,
    std::optional<std::string> replace_key,
    int debounce_window_ms,
    double now_mono_s) {
  const int timeout = std::max(1, timeout_ms.value_or(default_timeout_ms_));
  const int debounce_ms = std::max(0, debounce_window_ms);
  prune_expired(now_mono_s);
  prune_recent_replace_keys(now_mono_s, debounce_ms);

  if (replace_key.has_value() && !replace_key->empty()) {
    const auto existing_index = find_by_replace_key(*replace_key);
    const auto recent_it = recent_replace_touched_.find(*replace_key);
    const bool within_debounce =
        recent_it != recent_replace_touched_.end() &&
        debounce_ms > 0 &&
        (now_mono_s - recent_it->second) < (static_cast<double>(debounce_ms) / 1000.0);

    if (within_debounce) {
      if (existing_index.has_value()) {
        auto& existing = items_[*existing_index];
        DecisionQueueItem replaced{};
        replaced.queue_id = existing.queue_id;
        replaced.enqueued_at_monotonic = existing.enqueued_at_monotonic;
        replaced.valid_until_monotonic = now_mono_s + (static_cast<double>(timeout) / 1000.0);
        replaced.decision = std::move(decision);
        existing = replaced;
        metadata_[existing.queue_id] = ItemMeta{replace_key, now_mono_s};
        recent_replace_touched_[*replace_key] = now_mono_s;
        sort_items();
        return replaced;
      }
      return std::nullopt;
    }

    if (existing_index.has_value()) {
      auto& existing = items_[*existing_index];
      DecisionQueueItem replaced{};
      replaced.queue_id = existing.queue_id;
      replaced.enqueued_at_monotonic = existing.enqueued_at_monotonic;
      replaced.valid_until_monotonic = now_mono_s + (static_cast<double>(timeout) / 1000.0);
      replaced.decision = std::move(decision);
      existing = replaced;
      metadata_[existing.queue_id] = ItemMeta{replace_key, now_mono_s};
      recent_replace_touched_[*replace_key] = now_mono_s;
      sort_items();
      return replaced;
    }
  }

  DecisionQueueItem item{};
  item.queue_id = common::new_id();
  item.enqueued_at_monotonic = now_mono_s;
  item.valid_until_monotonic = now_mono_s + (static_cast<double>(timeout) / 1000.0);
  item.decision = std::move(decision);

  items_.push_back(item);
  metadata_[item.queue_id] = ItemMeta{replace_key, now_mono_s};
  if (replace_key.has_value() && !replace_key->empty()) {
    recent_replace_touched_[*replace_key] = now_mono_s;
  }
  sort_items();

  if (items_.size() > max_size_) {
    const auto dropped = pop_item_at_index(items_.size() - 1);
    if (dropped.has_value() && dropped->queue_id == item.queue_id) {
      return std::nullopt;
    }
  }
  return item;
}

std::optional<common::ArbitrationResult> DecisionQueue::pop_next(double now_mono_s) {
  prune_expired(now_mono_s);
  if (items_.empty()) {
    return std::nullopt;
  }
  const auto popped = pop_item_at_index(0);
  if (!popped.has_value()) {
    return std::nullopt;
  }
  return popped->decision;
}

std::optional<common::ArbitrationResult> DecisionQueue::pop_starved_oldest(
    int starvation_after_ms,
    std::unordered_set<common::EventPriority> priorities,
    double now_mono_s) {
  prune_expired(now_mono_s);
  if (items_.empty() || starvation_after_ms <= 0) {
    return std::nullopt;
  }
  const double threshold_s = static_cast<double>(starvation_after_ms) / 1000.0;

  std::optional<std::size_t> oldest_index{};
  double oldest_time = now_mono_s;
  for (std::size_t i = 0; i < items_.size(); ++i) {
    const auto& item = items_[i];
    if (!priorities.empty() && !priorities.contains(item.decision.priority)) {
      continue;
    }
    if ((now_mono_s - item.enqueued_at_monotonic) < threshold_s) {
      continue;
    }
    if (!oldest_index.has_value() || item.enqueued_at_monotonic < oldest_time) {
      oldest_index = i;
      oldest_time = item.enqueued_at_monotonic;
    }
  }

  if (!oldest_index.has_value()) {
    return std::nullopt;
  }
  const auto popped = pop_item_at_index(*oldest_index);
  if (!popped.has_value()) {
    return std::nullopt;
  }
  return popped->decision;
}

std::optional<DecisionQueueItem> DecisionQueue::drop_oldest(
    std::optional<common::EventPriority> priority,
    double now_mono_s) {
  prune_expired(now_mono_s);
  if (items_.empty()) {
    return std::nullopt;
  }
  if (!priority.has_value()) {
    return pop_item_at_index(0);
  }
  for (std::size_t i = 0; i < items_.size(); ++i) {
    if (items_[i].decision.priority == *priority) {
      return pop_item_at_index(i);
    }
  }
  return std::nullopt;
}

void DecisionQueue::prune_expired(double now_mono_s) {
  std::vector<DecisionQueueItem> active{};
  active.reserve(items_.size());
  for (const auto& item : items_) {
    if (item.valid_until_monotonic > now_mono_s) {
      active.push_back(item);
      continue;
    }
    metadata_.erase(item.queue_id);
  }
  items_ = std::move(active);
}

std::size_t DecisionQueue::size(double now_mono_s) {
  prune_expired(now_mono_s);
  return items_.size();
}

std::size_t DecisionQueue::count(
    std::optional<common::EventPriority> priority,
    double now_mono_s) {
  prune_expired(now_mono_s);
  if (!priority.has_value()) {
    return items_.size();
  }
  return static_cast<std::size_t>(std::count_if(
      items_.begin(),
      items_.end(),
      [&](const DecisionQueueItem& item) { return item.decision.priority == *priority; }));
}

bool DecisionQueue::has_replace_key(std::string_view replace_key, double now_mono_s) {
  prune_expired(now_mono_s);
  return find_by_replace_key(replace_key).has_value();
}

std::vector<DecisionQueueItem> DecisionQueue::items(
    std::optional<common::EventPriority> priority,
    double now_mono_s) {
  prune_expired(now_mono_s);
  if (!priority.has_value()) {
    return items_;
  }
  std::vector<DecisionQueueItem> filtered{};
  filtered.reserve(items_.size());
  for (const auto& item : items_) {
    if (item.decision.priority == *priority) {
      filtered.push_back(item);
    }
  }
  return filtered;
}

std::optional<std::string> DecisionQueue::replace_key_for(const std::string& queue_id) const {
  const auto it = metadata_.find(queue_id);
  if (it == metadata_.end()) {
    return std::nullopt;
  }
  return it->second.replace_key;
}

std::optional<DecisionQueueItem> DecisionQueue::drop_queue_id(
    const std::string& queue_id,
    double now_mono_s) {
  prune_expired(now_mono_s);
  for (std::size_t i = 0; i < items_.size(); ++i) {
    if (items_[i].queue_id == queue_id) {
      return pop_item_at_index(i);
    }
  }
  return std::nullopt;
}

void DecisionQueue::clear() {
  items_.clear();
  metadata_.clear();
  recent_replace_touched_.clear();
}

int DecisionQueue::priority_order(common::EventPriority priority) {
  return common::priority_rank(priority);
}

bool DecisionQueue::queue_item_less(const DecisionQueueItem& lhs, const DecisionQueueItem& rhs) {
  const auto lhs_rank = priority_order(lhs.decision.priority);
  const auto rhs_rank = priority_order(rhs.decision.priority);
  if (lhs_rank != rhs_rank) {
    return lhs_rank < rhs_rank;
  }
  return lhs.enqueued_at_monotonic < rhs.enqueued_at_monotonic;
}

void DecisionQueue::sort_items() {
  std::sort(items_.begin(), items_.end(), queue_item_less);
}

void DecisionQueue::prune_recent_replace_keys(double now_mono_s, int debounce_window_ms) {
  if (debounce_window_ms <= 0) {
    return;
  }
  const auto window_s = static_cast<double>(debounce_window_ms) / 1000.0;
  std::vector<std::string> stale{};
  stale.reserve(recent_replace_touched_.size());
  for (const auto& [key, touched_at] : recent_replace_touched_) {
    if ((now_mono_s - touched_at) >= window_s) {
      stale.push_back(key);
    }
  }
  for (const auto& key : stale) {
    recent_replace_touched_.erase(key);
  }
}

std::optional<std::size_t> DecisionQueue::find_by_replace_key(std::string_view replace_key) const {
  for (std::size_t i = 0; i < items_.size(); ++i) {
    const auto meta_it = metadata_.find(items_[i].queue_id);
    if (meta_it == metadata_.end() || !meta_it->second.replace_key.has_value()) {
      continue;
    }
    if (*meta_it->second.replace_key == replace_key) {
      return i;
    }
  }
  return std::nullopt;
}

std::optional<DecisionQueueItem> DecisionQueue::pop_item_at_index(std::size_t index) {
  if (index >= items_.size()) {
    return std::nullopt;
  }
  DecisionQueueItem item = items_[index];
  items_.erase(items_.begin() + static_cast<std::ptrdiff_t>(index));
  metadata_.erase(item.queue_id);
  return item;
}

}  // namespace robot_life_cpp::event_engine
