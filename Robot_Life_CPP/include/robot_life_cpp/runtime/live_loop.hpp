#pragma once

#include <atomic>
#include <cstddef>
#include <mutex>
#include <optional>
#include <queue>
#include <string>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/event_engine/arbitrator.hpp"
#include "robot_life_cpp/event_engine/scene_aggregator.hpp"
#include "robot_life_cpp/event_engine/stabilizer.hpp"

namespace robot_life_cpp::runtime {

struct LiveLoopConfig {
  double tick_hz{30.0};
  std::size_t max_pending_events{512};
  bool drop_when_full{true};
};

struct RuntimeSnapshot {
  bool running{false};
  double now_mono_s{0.0};
  std::size_t pending_events{0};
  std::size_t stable_events_last_tick{0};
  std::size_t scene_candidates_last_tick{0};
  std::optional<common::ArbitrationResult> last_decision{};
};

class LiveLoop {
 public:
  explicit LiveLoop(
      LiveLoopConfig config = {},
      event_engine::StabilizerRules stabilizer_rules = {},
      event_engine::SceneAggregatorRules aggregator_rules = {},
      event_engine::ArbitratorRules arbitrator_rules = {});

  void ingest(common::RawEvent event);
  bool tick();
  void run_for_ticks(std::size_t ticks);
  void reconfigure(
      LiveLoopConfig config,
      event_engine::StabilizerRules stabilizer_rules,
      event_engine::SceneAggregatorRules aggregator_rules,
      event_engine::ArbitratorRules arbitrator_rules);

  RuntimeSnapshot snapshot() const;
  std::optional<common::ArbitrationResult> last_decision() const;
  void stop();
  void reset();

 private:
  LiveLoopConfig config_;
  mutable std::mutex mu_;
  std::queue<common::RawEvent> pending_;
  event_engine::EventStabilizer stabilizer_{};
  event_engine::SceneAggregator aggregator_{};
  event_engine::Arbitrator arbitrator_{};
  std::optional<common::ArbitrationResult> last_decision_{};
  std::size_t stable_events_last_tick_{0};
  std::size_t scene_candidates_last_tick_{0};
  std::atomic<bool> running_{true};
};

}  // namespace robot_life_cpp::runtime
