#include "robot_life_cpp/runtime/live_loop.hpp"

#include <chrono>
#include <thread>

namespace robot_life_cpp::runtime {

namespace {
void normalize_live_loop_config(LiveLoopConfig* config) {
  if (config == nullptr) {
    return;
  }
  if (config->tick_hz < 1.0) {
    config->tick_hz = 1.0;
  }
  if (config->max_pending_events == 0) {
    config->max_pending_events = 1;
  }
}
}  // namespace

LiveLoop::LiveLoop(
    LiveLoopConfig config,
    event_engine::StabilizerRules stabilizer_rules,
    event_engine::SceneAggregatorRules aggregator_rules,
    event_engine::ArbitratorRules arbitrator_rules)
    : config_(std::move(config)),
      stabilizer_(std::move(stabilizer_rules)),
      aggregator_(std::move(aggregator_rules)),
      arbitrator_(std::move(arbitrator_rules)) {
  normalize_live_loop_config(&config_);
}

void LiveLoop::reconfigure(
    LiveLoopConfig config,
    event_engine::StabilizerRules stabilizer_rules,
    event_engine::SceneAggregatorRules aggregator_rules,
    event_engine::ArbitratorRules arbitrator_rules) {
  normalize_live_loop_config(&config);
  std::lock_guard<std::mutex> lock(mu_);
  config_ = std::move(config);
  stabilizer_ = event_engine::EventStabilizer{std::move(stabilizer_rules)};
  aggregator_ = event_engine::SceneAggregator{std::move(aggregator_rules)};
  arbitrator_ = event_engine::Arbitrator{std::move(arbitrator_rules)};
  last_decision_.reset();
  stable_events_last_tick_ = 0;
  scene_candidates_last_tick_ = 0;
}

void LiveLoop::ingest(common::RawEvent event) {
  std::lock_guard<std::mutex> lock(mu_);
  if (pending_.size() >= config_.max_pending_events) {
    if (config_.drop_when_full) {
      return;
    }
    pending_.pop();
  }
  pending_.push(std::move(event));
}

bool LiveLoop::tick() {
  if (!running_.load()) {
    return false;
  }

  std::vector<common::RawEvent> batch{};
  {
    std::lock_guard<std::mutex> lock(mu_);
    const auto batch_limit = std::min<std::size_t>(pending_.size(), 64);
    batch.reserve(batch_limit);
    for (std::size_t i = 0; i < batch_limit; ++i) {
      batch.push_back(std::move(pending_.front()));
      pending_.pop();
    }
  }

  const auto now = common::now_mono();
  std::vector<common::StableEvent> stable_events{};
  stable_events.reserve(batch.size());

  for (const auto& raw : batch) {
    auto stable = stabilizer_.process(raw, now);
    if (stable.has_value()) {
      stable_events.push_back(std::move(*stable));
    }
  }

  auto scenes = aggregator_.update(stable_events, now);
  auto decision = arbitrator_.decide(scenes, now);

  {
    std::lock_guard<std::mutex> lock(mu_);
    stable_events_last_tick_ = stable_events.size();
    scene_candidates_last_tick_ = scenes.size();
    if (decision.has_value()) {
      last_decision_ = std::move(*decision);
    }
  }
  return true;
}

void LiveLoop::run_for_ticks(std::size_t ticks) {
  const auto sleep_for = std::chrono::duration<double>(1.0 / config_.tick_hz);
  for (std::size_t i = 0; i < ticks; ++i) {
    if (!tick()) {
      return;
    }
    std::this_thread::sleep_for(sleep_for);
  }
}

RuntimeSnapshot LiveLoop::snapshot() const {
  std::lock_guard<std::mutex> lock(mu_);
  RuntimeSnapshot snap{};
  snap.running = running_.load();
  snap.now_mono_s = common::now_mono();
  snap.pending_events = pending_.size();
  snap.stable_events_last_tick = stable_events_last_tick_;
  snap.scene_candidates_last_tick = scene_candidates_last_tick_;
  snap.last_decision = last_decision_;
  return snap;
}

std::optional<common::ArbitrationResult> LiveLoop::last_decision() const {
  std::lock_guard<std::mutex> lock(mu_);
  return last_decision_;
}

void LiveLoop::stop() { running_.store(false); }

void LiveLoop::reset() {
  std::lock_guard<std::mutex> lock(mu_);
  while (!pending_.empty()) {
    pending_.pop();
  }
  stabilizer_.reset();
  aggregator_.reset();
  arbitrator_.reset();
  last_decision_.reset();
  stable_events_last_tick_ = 0;
  scene_candidates_last_tick_ = 0;
  running_.store(true);
}

}  // namespace robot_life_cpp::runtime
