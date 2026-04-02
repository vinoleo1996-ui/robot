#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct DecisionQueueItem {
  std::string queue_id;
  double enqueued_at_monotonic{0.0};
  double valid_until_monotonic{0.0};
  common::ArbitrationResult decision{};
};

class DecisionQueue {
 public:
  explicit DecisionQueue(int default_timeout_ms = 5000, std::size_t max_size = 32);

  std::optional<DecisionQueueItem> enqueue(
      common::ArbitrationResult decision,
      std::optional<int> timeout_ms = std::nullopt,
      std::optional<std::string> replace_key = std::nullopt,
      int debounce_window_ms = 0,
      double now_mono_s = common::now_mono());

  std::optional<common::ArbitrationResult> pop_next(double now_mono_s = common::now_mono());

  std::optional<common::ArbitrationResult> pop_starved_oldest(
      int starvation_after_ms,
      std::unordered_set<common::EventPriority> priorities = {},
      double now_mono_s = common::now_mono());

  std::optional<DecisionQueueItem> drop_oldest(
      std::optional<common::EventPriority> priority = std::nullopt,
      double now_mono_s = common::now_mono());

  void prune_expired(double now_mono_s = common::now_mono());

  std::size_t size(double now_mono_s = common::now_mono());
  std::size_t count(
      std::optional<common::EventPriority> priority = std::nullopt,
      double now_mono_s = common::now_mono());

  bool has_replace_key(std::string_view replace_key, double now_mono_s = common::now_mono());
  std::vector<DecisionQueueItem> items(
      std::optional<common::EventPriority> priority = std::nullopt,
      double now_mono_s = common::now_mono());

  std::optional<std::string> replace_key_for(const std::string& queue_id) const;
  std::optional<DecisionQueueItem> drop_queue_id(
      const std::string& queue_id,
      double now_mono_s = common::now_mono());

  void clear();

 private:
  struct ItemMeta {
    std::optional<std::string> replace_key{};
    double touched_at_monotonic{0.0};
  };

  static int priority_order(common::EventPriority priority);
  static bool queue_item_less(const DecisionQueueItem& lhs, const DecisionQueueItem& rhs);

  void sort_items();
  void prune_recent_replace_keys(double now_mono_s, int debounce_window_ms);
  std::optional<std::size_t> find_by_replace_key(std::string_view replace_key) const;
  std::optional<DecisionQueueItem> pop_item_at_index(std::size_t index);

  int default_timeout_ms_{5000};
  std::size_t max_size_{32};
  std::vector<DecisionQueueItem> items_{};
  std::unordered_map<std::string, ItemMeta> metadata_{};
  std::unordered_map<std::string, double> recent_replace_touched_{};
};

}  // namespace robot_life_cpp::event_engine
