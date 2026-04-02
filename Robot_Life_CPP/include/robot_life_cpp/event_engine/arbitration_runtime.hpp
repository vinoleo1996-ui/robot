#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/event_engine/arbitrator.hpp"
#include "robot_life_cpp/event_engine/decision_queue.hpp"

namespace robot_life_cpp::event_engine {

struct ArbitrationBatchOutcome {
  common::SceneCandidate scene{};
  common::ArbitrationResult decision{};
  std::string outcome{"idle"};
  bool executed{false};
};

class ArbitrationRuntime {
 public:
  ArbitrationRuntime();

  explicit ArbitrationRuntime(
      Arbitrator arbitrator,
      DecisionQueue queue,
      int batch_window_ms = 40,
      std::size_t p1_queue_limit = 3,
      std::size_t p2_queue_limit = 4,
      int starvation_after_ms = 1500);

  std::optional<common::ArbitrationResult> submit(
      const common::SceneCandidate& scene,
      std::optional<common::EventPriority> current_priority = std::nullopt,
      std::optional<int> batch_window_ms = std::nullopt,
      double now_mono_s = common::now_mono());

  std::vector<ArbitrationBatchOutcome> submit_batch(
      const std::vector<common::SceneCandidate>& scenes,
      std::optional<common::EventPriority> current_priority = std::nullopt,
      std::optional<int> batch_window_ms = std::nullopt,
      double now_mono_s = common::now_mono());

  std::optional<common::ArbitrationResult> complete_active(double now_mono_s = common::now_mono());
  void clear();

  std::size_t pending(double now_mono_s = common::now_mono());
  std::optional<common::EventPriority> active_priority() const;
  const std::string& last_outcome() const;
  std::optional<common::ArbitrationResult> last_decision() const;
  std::unordered_map<std::string, int> outcome_counts() const;

 private:
  static std::string decision_key(
      const common::SceneCandidate& scene,
      const common::ArbitrationResult& decision);
  static std::string target_from_key(const std::string& key);
  static int queue_timeout_ms(common::EventPriority priority);

  ArbitrationBatchOutcome submit_scene(
      const common::SceneCandidate& scene,
      std::optional<common::EventPriority> current_priority,
      std::optional<int> batch_window_ms,
      double now_mono_s);

  std::string enqueue_with_replace(
      const common::SceneCandidate& scene,
      const common::ArbitrationResult& decision,
      std::optional<int> batch_window_ms,
      double now_mono_s);

  bool should_enqueue_with_replace(const common::ArbitrationResult& decision) const;
  int resolved_batch_window_ms(std::optional<int> batch_window_ms, common::EventPriority priority) const;
  std::size_t queue_limit(common::EventPriority priority) const;
  void evict_for_fairness(common::EventPriority priority, const std::optional<std::string>& incoming_key);
  void remember_decision_key(const common::ArbitrationResult& decision, const std::optional<std::string>& key);
  void prune_recent_keys(common::EventPriority priority, double now_mono_s, std::optional<int> batch_window_ms);
  std::unordered_map<std::string, double>& recent_key_store(common::EventPriority priority);
  void record_outcome(const std::string& outcome);

  Arbitrator arbitrator_{};
  DecisionQueue queue_{};
  int batch_window_ms_{40};
  std::size_t p1_queue_limit_{3};
  std::size_t p2_queue_limit_{4};
  int starvation_after_ms_{1500};

  std::optional<common::EventPriority> active_priority_{};
  std::optional<std::string> active_decision_key_{};
  std::string last_outcome_{"idle"};
  std::optional<common::ArbitrationResult> last_decision_{};
  std::unordered_map<std::string, std::string> decision_keys_{};
  std::unordered_map<std::string, double> recent_p1_keys_{};
  std::unordered_map<std::string, double> recent_p2_keys_{};
  std::unordered_map<std::string, int> outcome_counts_{
      {"idle", 0},
      {"executed", 0},
      {"queued", 0},
      {"debounced", 0},
      {"dropped", 0},
      {"dequeued", 0},
  };
};

}  // namespace robot_life_cpp::event_engine
