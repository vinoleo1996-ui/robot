#include "robot_life_cpp/runtime/live_loop.hpp"

#include <algorithm>
#include <chrono>
#include <thread>
#include <unordered_map>

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

event_engine::SceneAggregatorRules normalize_fast_reaction_scene_rules(event_engine::SceneAggregatorRules rules) {
  auto& exact = rules.taxonomy.event_scene_exact;
  exact.try_emplace("familiar_face_detected", "greeting_familiar_scene");
  exact.try_emplace("stranger_face_detected", "greeting_stranger_scene");
  exact.try_emplace("gesture_detected", "gesture_pose_response_scene");
  exact.try_emplace("wave_detected", "gesture_pose_response_scene");
  exact.try_emplace("face_attention_detected", "attention_detection_scene");
  exact.try_emplace("gaze_sustained_detected", "attention_detection_scene");
  exact.try_emplace("person_present_detected", "attention_detection_scene");
  exact.try_emplace("motion_detected", "moving_object_attention_scene");
  exact.try_emplace("approaching_detected", "moving_object_attention_scene");
  exact.try_emplace("leaving_detected", "moving_object_attention_scene");
  exact.try_emplace("object_detected", "moving_object_attention_scene");
  exact.try_emplace("loud_sound_detected", "special_audio_attention_scene");
  exact.try_emplace("collision_warning_detected", "special_audio_attention_scene");
  exact.try_emplace("emergency_stop_detected", "special_audio_attention_scene");

  rules.scene_bias.try_emplace("greeting_familiar_scene", 1.25);
  rules.scene_bias.try_emplace("greeting_stranger_scene", 1.1);
  rules.scene_bias.try_emplace("gesture_pose_response_scene", 1.2);
  rules.scene_bias.try_emplace("special_audio_attention_scene", 1.35);
  rules.scene_bias.try_emplace("moving_object_attention_scene", 1.15);
  rules.scene_bias.try_emplace("attention_detection_scene", 1.05);
  return rules;
}

bool is_broad_scene_type(const std::string& scene_type) {
  return scene_type == "generic_event" || scene_type == "human_presence" || scene_type == "speech_activity" ||
         scene_type == "motion_alert" || scene_type == "body_pose" || scene_type == "attention_detection_scene";
}

int execution_duration_ms(common::EventPriority priority) {
  switch (priority) {
    case common::EventPriority::P0:
      return 800;
    case common::EventPriority::P1:
      return 1200;
    case common::EventPriority::P2:
      return 1500;
    case common::EventPriority::P3:
      return 1000;
  }
  return 1000;
}

bool should_override_scene_type(const std::string& primary_scene_type, const std::string& hint_scene_type) {
  return primary_scene_type != hint_scene_type && is_broad_scene_type(primary_scene_type);
}

std::optional<std::size_t> find_scene_for_hint(
    const std::vector<common::SceneCandidate>& primary_scenes,
    const common::SceneCandidate& hint) {
  std::optional<std::size_t> broad_target_match{};
  std::optional<std::size_t> any_target_match{};
  for (std::size_t i = 0; i < primary_scenes.size(); ++i) {
    const auto& primary = primary_scenes[i];
    if (primary.target_id.has_value() && hint.target_id.has_value() && *primary.target_id == *hint.target_id) {
      if (primary.scene_type == hint.scene_type) {
        return i;
      }
      if (!any_target_match.has_value()) {
        any_target_match = i;
      }
      if (is_broad_scene_type(primary.scene_type) && !broad_target_match.has_value()) {
        broad_target_match = i;
      }
      continue;
    }
    if (!primary.target_id.has_value() && !hint.target_id.has_value() && primary.scene_type == hint.scene_type) {
      return i;
    }
  }
  if (broad_target_match.has_value()) {
    return broad_target_match;
  }
  return any_target_match;
}

void merge_scene_hints(
    std::vector<common::SceneCandidate>* primary_scenes,
    const std::vector<common::SceneCandidate>& hints) {
  if (primary_scenes == nullptr || primary_scenes->empty() || hints.empty()) {
    return;
  }

  for (const auto& hint : hints) {
    const auto index = find_scene_for_hint(*primary_scenes, hint);
    if (!index.has_value()) {
      continue;
    }

    auto& primary = (*primary_scenes)[*index];
    primary.payload["scene_coordinator_scene_id"] = hint.scene_id;
    primary.payload["scene_coordinator_scene_type"] = hint.scene_type;
    primary.payload["scene_coordinator_trace_id"] = hint.trace_id;
    primary.payload["scene_coordinator_score_hint"] = std::to_string(hint.score_hint);
    primary.payload["scene_coordinator_role"] = "bias_hint";
    if (const auto behavior_it = hint.payload.find("scene_behavior_hint");
        behavior_it != hint.payload.end() && !behavior_it->second.empty()) {
      primary.payload["scene_coordinator_behavior_hint"] = behavior_it->second;
    }
    if (const auto origin_it = hint.payload.find("scene_origin");
        origin_it != hint.payload.end() && !origin_it->second.empty()) {
      primary.payload["scene_coordinator_source"] = origin_it->second;
    } else if (const auto source_it = hint.payload.find("scene_source");
               source_it != hint.payload.end() && !source_it->second.empty()) {
      primary.payload["scene_coordinator_source"] = source_it->second;
    }
    if (should_override_scene_type(primary.scene_type, hint.scene_type)) {
      primary.scene_type = hint.scene_type;
    }
    primary.score_hint = std::clamp(primary.score_hint + (hint.score_hint * 0.1), 0.0, 10.0);
    primary.valid_until_monotonic = std::max(primary.valid_until_monotonic, hint.valid_until_monotonic);
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
      aggregator_(aggregator_rules),
      arbitrator_(std::move(arbitrator_rules)) {
  normalize_live_loop_config(&config_);
  const auto normalized_aggregator_rules = normalize_fast_reaction_scene_rules(std::move(aggregator_rules));
  const auto taxonomy = normalized_aggregator_rules.taxonomy;
  const auto scene_ttl_s = normalized_aggregator_rules.scene_ttl_s;
  aggregator_ = event_engine::SceneAggregator{normalized_aggregator_rules};
  cooldown_manager_ = event_engine::CooldownManager{
      3.0,
      {},
      20.0,
      3,
      taxonomy,
  };
  scene_coordinator_.reconfigure(
      SceneCoordinatorRules{.scene_ttl_s = scene_ttl_s, .min_confidence = 0.0});
}

void LiveLoop::reconfigure(
    LiveLoopConfig config,
    event_engine::StabilizerRules stabilizer_rules,
    event_engine::SceneAggregatorRules aggregator_rules,
    event_engine::ArbitratorRules arbitrator_rules) {
  normalize_live_loop_config(&config);
  const auto normalized_aggregator_rules = normalize_fast_reaction_scene_rules(std::move(aggregator_rules));
  const auto taxonomy = normalized_aggregator_rules.taxonomy;
  const auto scene_ttl_s = normalized_aggregator_rules.scene_ttl_s;
  std::lock_guard<std::mutex> lock(mu_);
  config_ = std::move(config);
  stabilizer_ = event_engine::EventStabilizer{std::move(stabilizer_rules)};
  aggregator_ = event_engine::SceneAggregator{std::move(normalized_aggregator_rules)};
  arbitrator_ = event_engine::Arbitrator{std::move(arbitrator_rules)};
  cooldown_manager_ = event_engine::CooldownManager{
      3.0,
      {},
      20.0,
      3,
      taxonomy,
  };
  scene_coordinator_.reconfigure(
      SceneCoordinatorRules{.scene_ttl_s = scene_ttl_s, .min_confidence = 0.0});
  target_governor_.reset();
  execution_manager_ = ExecutionManager{};
  active_target_id_.reset();
  active_scene_type_.reset();
  last_decision_.reset();
  last_execution_.reset();
  governed_events_last_tick_ = 0;
  dropped_events_last_tick_ = 0;
  stable_events_last_tick_ = 0;
  scene_candidates_last_tick_ = 0;
  executions_last_tick_ = 0;
  execution_history_size_ = 0;
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
  std::vector<common::RawEvent> governed_events{};
  governed_events.reserve(batch.size());
  std::size_t dropped_events = 0;
  for (auto& raw : batch) {
    auto governed = target_governor_.preprocess(std::move(raw), now);
    if (!governed.has_value()) {
      dropped_events += 1;
      continue;
    }
    governed_events.push_back(std::move(*governed));
  }

  std::vector<common::StableEvent> stable_events{};
  stable_events.reserve(governed_events.size());

  for (const auto& raw : governed_events) {
    auto stable = stabilizer_.process(raw, now);
    if (stable.has_value()) {
      stable_events.push_back(std::move(*stable));
    }
  }

  auto scenes = aggregator_.update(stable_events, now);
  auto coordinated_scenes = scene_coordinator_.derive(stable_events, now);
  merge_scene_hints(&scenes, coordinated_scenes);

  std::vector<common::SceneCandidate> filtered_scenes{};
  filtered_scenes.reserve(scenes.size());
  const auto active_target = target_governor_.active_target_id(now);
  std::optional<std::string> active_behavior_id{};
  {
    std::lock_guard<std::mutex> lock(mu_);
    if (last_decision_.has_value()) {
      active_behavior_id = last_decision_->target_behavior;
    }
  }
  for (const auto& scene : scenes) {
    event_engine::CooldownCheckInput cooldown_input{};
    cooldown_input.scene_type = scene.scene_type;
    cooldown_input.target_id = scene.target_id;
    cooldown_input.priority = arbitrator_.resolve_scene_priority(scene.scene_type);
    cooldown_input.active_target_id = active_target;
    cooldown_input.active_behavior_id = active_behavior_id;
    cooldown_input.robot_busy = false;
    const auto check = cooldown_manager_.check(cooldown_input, now);
    if (!check.allowed) {
      continue;
    }
    filtered_scenes.push_back(scene);
  }

  auto decision = arbitrator_.decide(filtered_scenes, now);
  std::optional<common::ExecutionResult> execution{};
  if (decision.has_value()) {
    if (decision->scene_type.has_value()) {
      cooldown_manager_.record_execution(*decision->scene_type, decision->target_id, now);
    }
    target_governor_.record_decision(*decision, now);
    execution = execution_manager_.dispatch_decision(*decision, execution_duration_ms(decision->priority), now);
  }
  const auto governor_snapshot = target_governor_.snapshot(now);

  {
    std::lock_guard<std::mutex> lock(mu_);
    governed_events_last_tick_ = governed_events.size();
    dropped_events_last_tick_ = dropped_events;
    stable_events_last_tick_ = stable_events.size();
    scene_candidates_last_tick_ = filtered_scenes.size();
    executions_last_tick_ = execution.has_value() ? 1U : 0U;
    execution_history_size_ = execution_manager_.history().size();
    active_target_id_ = governor_snapshot.active_target_id;
    active_scene_type_ = governor_snapshot.active_scene_type;
    if (decision.has_value()) {
      last_decision_ = std::move(*decision);
    }
    if (execution.has_value()) {
      last_execution_ = std::move(*execution);
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
  snap.governed_events_last_tick = governed_events_last_tick_;
  snap.dropped_events_last_tick = dropped_events_last_tick_;
  snap.stable_events_last_tick = stable_events_last_tick_;
  snap.scene_candidates_last_tick = scene_candidates_last_tick_;
  snap.executions_last_tick = executions_last_tick_;
  snap.execution_history_size = execution_history_size_;
  snap.active_target_id = active_target_id_;
  snap.active_scene_type = active_scene_type_;
  snap.last_decision = last_decision_;
  snap.last_execution = last_execution_;
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
  cooldown_manager_.reset();
  target_governor_.reset();
  execution_manager_ = ExecutionManager{};
  last_decision_.reset();
  last_execution_.reset();
  governed_events_last_tick_ = 0;
  dropped_events_last_tick_ = 0;
  stable_events_last_tick_ = 0;
  scene_candidates_last_tick_ = 0;
  executions_last_tick_ = 0;
  execution_history_size_ = 0;
  active_target_id_.reset();
  active_scene_type_.reset();
  running_.store(true);
}

}  // namespace robot_life_cpp::runtime
