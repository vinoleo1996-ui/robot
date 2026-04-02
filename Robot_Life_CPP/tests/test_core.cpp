#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <thread>
#include <unordered_set>

#include "robot_life_cpp/behavior/executor.hpp"
#include "robot_life_cpp/behavior/resources.hpp"
#include "robot_life_cpp/behavior/safety_guard.hpp"
#include "robot_life_cpp/bridge/deepstream_protocol.hpp"
#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/common/visual_contract.hpp"
#include "robot_life_cpp/event_engine/arbitration_runtime.hpp"
#include "robot_life_cpp/event_engine/cooldown_manager.hpp"
#include "robot_life_cpp/event_engine/decision_queue.hpp"
#include "robot_life_cpp/event_engine/entity_tracker.hpp"
#include "robot_life_cpp/event_engine/stabilizer.hpp"
#include "robot_life_cpp/event_engine/temporal_event_layer.hpp"
#include "robot_life_cpp/migration/module_catalog.hpp"
#include "robot_life_cpp/perception/deepstream_adapter.hpp"
#include "robot_life_cpp/perception/deepstream_export_contract.hpp"
#include "robot_life_cpp/perception/deepstream_exporter.hpp"
#include "robot_life_cpp/perception/deepstream_graph.hpp"
#include "robot_life_cpp/perception/deepstream_process_backend.hpp"
#include "robot_life_cpp/perception/deepstream_runner.hpp"
#include "robot_life_cpp/runtime/execution_manager.hpp"
#include "robot_life_cpp/runtime/event_injector.hpp"
#include "robot_life_cpp/runtime/execution_support.hpp"
#include "robot_life_cpp/runtime/health_monitor.hpp"
#include "robot_life_cpp/runtime/load_shedder.hpp"
#include "robot_life_cpp/runtime/life_state.hpp"
#include "robot_life_cpp/runtime/live_loop.hpp"
#include "robot_life_cpp/runtime/pipeline_factory.hpp"
#include "robot_life_cpp/runtime/profile_registry.hpp"
#include "robot_life_cpp/runtime/runtime_tuning.hpp"
#include "robot_life_cpp/runtime/telemetry.hpp"
#include "robot_life_cpp/runtime/ui_demo.hpp"

namespace {
robot_life_cpp::common::RawEvent build_event(const std::string& event_type,
                                             const std::string& key,
                                             double confidence,
                                             double ts) {
  robot_life_cpp::common::RawEvent e{};
  e.event_id = robot_life_cpp::common::new_id();
  e.trace_id = robot_life_cpp::common::new_id();
  e.event_type = event_type;
  e.priority = robot_life_cpp::common::EventPriority::P1;
  e.timestamp_monotonic = ts;
  e.confidence = confidence;
  e.source = "test";
  e.cooldown_key = key;
  e.payload = {{"confidence", std::to_string(confidence)}};
  return e;
}

robot_life_cpp::common::ArbitrationResult build_decision(
    std::string behavior_id,
    robot_life_cpp::common::EventPriority priority,
    robot_life_cpp::common::DecisionMode mode = robot_life_cpp::common::DecisionMode::Queue) {
  robot_life_cpp::common::ArbitrationResult decision{};
  decision.decision_id = robot_life_cpp::common::new_id();
  decision.trace_id = robot_life_cpp::common::new_id();
  decision.target_behavior = std::move(behavior_id);
  decision.priority = priority;
  decision.mode = mode;
  decision.required_resources = {"camera"};
  decision.reason = "unit-test";
  return decision;
}

robot_life_cpp::common::SceneCandidate build_scene(
    std::string scene_type,
    double score,
    double valid_until,
    std::optional<std::string> target_id = std::nullopt) {
  robot_life_cpp::common::SceneCandidate scene{};
  scene.scene_id = robot_life_cpp::common::new_id();
  scene.trace_id = robot_life_cpp::common::new_id();
  scene.scene_type = std::move(scene_type);
  scene.score_hint = score;
  scene.valid_until_monotonic = valid_until;
  scene.target_id = std::move(target_id);
  return scene;
}

robot_life_cpp::common::StableEvent build_stable_event(
    std::string event_type,
    std::optional<std::string> target_id,
    double valid_until) {
  robot_life_cpp::common::StableEvent event{};
  event.stable_event_id = robot_life_cpp::common::new_id();
  event.base_event_id = robot_life_cpp::common::new_id();
  event.trace_id = robot_life_cpp::common::new_id();
  event.event_type = std::move(event_type);
  event.priority = robot_life_cpp::common::EventPriority::P2;
  event.valid_until_monotonic = valid_until;
  event.stabilized_by = {"stabilizer"};
  if (target_id.has_value()) {
    event.payload["target_id"] = *target_id;
  }
  return event;
}

robot_life_cpp::common::DetectionResult build_detection(
    std::string detector,
    std::string event_type,
    robot_life_cpp::common::Payload payload = {}) {
  robot_life_cpp::common::DetectionResult d{};
  d.trace_id = robot_life_cpp::common::new_id();
  d.source = "test";
  d.detector = std::move(detector);
  d.event_type = std::move(event_type);
  d.timestamp = robot_life_cpp::common::now_wall();
  d.confidence = 0.9;
  d.payload = std::move(payload);
  return d;
}

robot_life_cpp::perception::DeepStreamFrameMetadata build_frame_metadata(
    std::string frame_id,
    robot_life_cpp::perception::DeepStreamObjectMetadata object) {
  robot_life_cpp::perception::DeepStreamFrameMetadata frame{};
  frame.source = "front_cam";
  frame.camera_id = "front_cam";
  frame.frame_id = std::move(frame_id);
  frame.timestamp = robot_life_cpp::common::now_wall();
  frame.objects.push_back(std::move(object));
  return frame;
}

std::vector<robot_life_cpp::common::DetectionResult> export_and_adapt(
    const std::vector<robot_life_cpp::perception::DeepStreamFrameMetadata>& frames) {
  robot_life_cpp::perception::DeepStreamExporter exporter{};
  robot_life_cpp::perception::DeepStreamAdapter adapter{};
  std::vector<robot_life_cpp::common::DetectionResult> detections{};
  for (const auto& frame : frames) {
    const auto lines = exporter.export_frame_lines(frame);
    for (const auto& line : lines) {
      const auto envelope = robot_life_cpp::bridge::parse_deepstream_line(line);
      assert(envelope.has_value());
      auto detection = adapter.adapt_detection(*envelope);
      if (detection.has_value()) {
        detections.push_back(std::move(*detection));
      }
    }
  }
  return detections;
}

std::optional<robot_life_cpp::common::ArbitrationResult> run_event_flow(
    const std::vector<robot_life_cpp::perception::DeepStreamFrameMetadata>& frames,
    std::vector<robot_life_cpp::common::RawEvent>* emitted_events = nullptr) {
  robot_life_cpp::runtime::DetectionEventInjector injector{
      {.dedupe_window_s = 0.0, .cooldown_window_s = 0.0, .max_events_per_batch = 8}};
  robot_life_cpp::runtime::LiveLoop loop{};

  const auto detections = export_and_adapt(frames);
  const auto events = injector.build_events(detections, 120.0);
  for (const auto& event : events) {
    loop.ingest(event);
  }
  const bool ok = loop.tick();
  assert(ok);
  if (emitted_events != nullptr) {
    *emitted_events = events;
  }
  return loop.last_decision();
}

class ScopedEnvVar {
 public:
  ScopedEnvVar(std::string key, std::string value) : key_(std::move(key)) {
    const char* existing = std::getenv(key_.c_str());
    if (existing != nullptr) {
      had_previous_ = true;
      previous_ = existing;
    }
    setenv(key_.c_str(), value.c_str(), 1);
  }

  ~ScopedEnvVar() {
    if (had_previous_) {
      setenv(key_.c_str(), previous_.c_str(), 1);
    } else {
      unsetenv(key_.c_str());
    }
  }

 private:
  std::string key_;
  std::string previous_;
  bool had_previous_{false};
};

class ScopedCurrentPath {
 public:
  explicit ScopedCurrentPath(const std::filesystem::path& path) : previous_(std::filesystem::current_path()) {
    std::filesystem::current_path(path);
  }

  ~ScopedCurrentPath() { std::filesystem::current_path(previous_); }

 private:
  std::filesystem::path previous_;
};

void test_live_loop_smoke() {
  robot_life_cpp::runtime::LiveLoop loop{};
  const auto base = robot_life_cpp::common::now_mono();
  auto e1 = build_event("speech_activity", "speech:test", 0.9, base);
  auto e2 = build_event("speech_activity", "speech:test", 0.91, base + 0.03);
  loop.ingest(std::move(e1));
  loop.ingest(std::move(e2));
  const bool ok = loop.tick();
  assert(ok);
  const auto snap = loop.snapshot();
  assert(snap.stable_events_last_tick >= 1);
  assert(snap.scene_candidates_last_tick >= 1);
}

void test_hysteresis_hold_and_release() {
  robot_life_cpp::event_engine::StabilizerRules rules{};
  rules.debounce_count = 1;
  rules.cooldown_s = 0.0;
  rules.dedup_window_s = 0.0;
  rules.hysteresis_threshold = 0.7;
  rules.hysteresis_transition_high = 0.85;
  rules.hysteresis_transition_low = 0.6;
  robot_life_cpp::event_engine::EventStabilizer stabilizer{rules};

  auto e1 = build_event("gesture_wave", "gesture:test", 0.90, 100.0);
  auto e2 = build_event("gesture_wave", "gesture:test", 0.65, 100.1);
  auto e3 = build_event("gesture_wave", "gesture:test", 0.55, 100.2);

  auto s1 = stabilizer.process(e1, 100.0);
  auto s2 = stabilizer.process(e2, 100.1);
  auto s3 = stabilizer.process(e3, 100.2);
  assert(s1.has_value());
  assert(s2.has_value());
  assert(!s3.has_value());
}

void test_module_catalog_uniqueness() {
  const auto& catalog = robot_life_cpp::migration::module_catalog();
  assert(!catalog.empty());
  std::unordered_set<std::string> python_paths{};
  std::unordered_set<std::string> cpp_targets{};
  for (const auto& item : catalog) {
    const auto [_, inserted_py] = python_paths.insert(item.python_module_path);
    assert(inserted_py);
    const auto [__, inserted_cpp] = cpp_targets.insert(item.cpp_target_unit);
    assert(inserted_cpp);
  }
}

void test_decision_queue_priority_and_replace() {
  robot_life_cpp::event_engine::DecisionQueue queue{5000, 8};
  auto p2 = build_decision("low", robot_life_cpp::common::EventPriority::P2);
  auto p0 = build_decision("high", robot_life_cpp::common::EventPriority::P0);
  auto queued_p2 = queue.enqueue(std::move(p2), 5000, std::nullopt, 0, 10.0);
  auto queued_p0 = queue.enqueue(std::move(p0), 5000, std::nullopt, 0, 10.1);
  assert(queued_p2.has_value());
  assert(queued_p0.has_value());
  auto first = queue.pop_next(10.2);
  assert(first.has_value());
  assert(first->priority == robot_life_cpp::common::EventPriority::P0);

  robot_life_cpp::event_engine::DecisionQueue replace_queue{5000, 4};
  auto first_decision = build_decision("first", robot_life_cpp::common::EventPriority::P1);
  auto second_decision = build_decision("second", robot_life_cpp::common::EventPriority::P1);
  auto inserted = replace_queue.enqueue(
      std::move(first_decision), 5000, std::optional<std::string>{"scene:any:perform"}, 0, 20.0);
  auto replaced = replace_queue.enqueue(
      std::move(second_decision), 5000, std::optional<std::string>{"scene:any:perform"}, 0, 20.2);
  assert(inserted.has_value());
  assert(replaced.has_value());
  assert(replace_queue.size(20.3) == 1);
  auto final_item = replace_queue.pop_next(20.3);
  assert(final_item.has_value());
  assert(final_item->target_behavior == "second");
}

void test_cooldown_manager_global_and_scene_rules() {
  robot_life_cpp::event_engine::CooldownManager manager{
      1.0, {{"attention_scene", 2.0}}, 10.0, 3};

  robot_life_cpp::event_engine::CooldownCheckInput input{};
  input.scene_type = "attention_scene";
  input.target_id = "user-a";
  input.priority = robot_life_cpp::common::EventPriority::P2;

  auto first = manager.check(input, 100.0);
  assert(first.allowed);
  manager.record_execution("attention_scene", "user-a", 100.0);

  auto blocked_global = manager.check(input, 100.2);
  assert(!blocked_global.allowed);
  assert(blocked_global.reason.find("global_cooldown:") != std::string::npos);

  input.priority = robot_life_cpp::common::EventPriority::P1;
  auto bypass_p1 = manager.check(input, 100.2);
  assert(bypass_p1.allowed);

  input.priority = robot_life_cpp::common::EventPriority::P2;
  auto blocked_scene = manager.check(input, 101.2);
  assert(!blocked_scene.allowed);
  assert(blocked_scene.reason.find("scene_cooldown:attention_scene:") != std::string::npos);

  auto allowed_after = manager.check(input, 102.2);
  assert(allowed_after.allowed);
}

void test_cooldown_manager_uses_configured_proactive_scenes() {
  robot_life_cpp::common::SceneTaxonomyRules taxonomy{};
  taxonomy.proactive_scenes = {"custom_scene"};
  robot_life_cpp::event_engine::CooldownManager manager{
      0.0, {{"custom_scene", 0.0}}, 10.0, 1, taxonomy};

  manager.record_execution("custom_scene", "user-a", 100.0);

  robot_life_cpp::event_engine::CooldownCheckInput input{};
  input.scene_type = "custom_scene";
  input.target_id = "user-a";
  input.priority = robot_life_cpp::common::EventPriority::P2;

  const auto blocked = manager.check(input, 100.2);
  assert(!blocked.allowed);
  assert(blocked.reason.find("saturation:") != std::string::npos);
}

void test_arbitration_runtime_queue_and_dequeue() {
  robot_life_cpp::event_engine::ArbitratorRules rules{};
  rules.decision_cooldown_s = 0.0;
  robot_life_cpp::event_engine::Arbitrator arbitrator{rules};
  robot_life_cpp::event_engine::DecisionQueue queue{5000, 8};
  robot_life_cpp::event_engine::ArbitrationRuntime runtime{
      std::move(arbitrator), std::move(queue), 40, 2, 2, 1000};

  auto active_scene = build_scene("gesture_interaction", 1.0, 200.0, "user-a");
  auto low_scene = build_scene("generic_event", 0.5, 200.0, "user-a");

  auto active = runtime.submit(active_scene, std::nullopt, std::nullopt, 150.0);
  assert(active.has_value());
  assert(runtime.active_priority().has_value());

  auto queued = runtime.submit(low_scene, std::nullopt, std::nullopt, 150.1);
  assert(!queued.has_value());
  assert(runtime.pending(150.1) == 1);
  assert(runtime.last_outcome() == "queued");

  auto drained = runtime.complete_active(150.2);
  assert(drained.has_value());
  assert(drained->mode == robot_life_cpp::common::DecisionMode::Execute);
  assert(drained->reason.find("dequeued:") == 0);
  assert(runtime.pending(150.3) == 0);
}

void test_temporal_event_layer_derives_gaze_and_wave() {
  robot_life_cpp::event_engine::TemporalEventLayer layer{};

  auto gaze_start = build_stable_event("gaze_sustained_detected", "user-a", 20.0);
  auto first = layer.process(gaze_start, 10.0);
  assert(first.size() == 2);
  assert(first[1].event_type == "gaze_hold_start_detected");

  auto gaze_active = build_stable_event("gaze_sustained_detected", "user-a", 20.0);
  auto second = layer.process(gaze_active, 10.2);
  assert(second.size() == 2);
  assert(second[1].event_type == "gaze_hold_active_detected");

  auto gaze_away = build_stable_event("gaze_away_detected", "user-a", 20.0);
  auto third = layer.process(gaze_away, 10.4);
  assert(third.size() == 3);
  assert(third[1].event_type == "gaze_hold_end_detected");
  assert(third[2].event_type == "attention_lost_detected");

  auto gesture = build_stable_event("gesture_detected", std::nullopt, 20.0);
  gesture.payload["raw_event_type"] = "gesture_waving";
  auto fourth = layer.process(gesture, 10.6);
  assert(fourth.size() == 2);
  assert(fourth[1].event_type == "wave_detected");
}

void test_entity_tracker_reuses_identity_tracks() {
  robot_life_cpp::event_engine::EntityTracker tracker{};

  std::vector<std::pair<std::string, robot_life_cpp::common::DetectionResult>> first_batch{};
  first_batch.emplace_back(
      "face",
      build_detection("insightface", "familiar_face_detected", {{"target_id", "alice"}}));
  auto first = tracker.associate_batch(first_batch, 30.0);
  assert(first.size() == 1);
  const auto first_track_id = first[0].second.payload.at("track_id");
  assert(first_track_id.rfind("person_track_", 0) == 0);

  std::vector<std::pair<std::string, robot_life_cpp::common::DetectionResult>> second_batch{};
  second_batch.emplace_back(
      "gaze",
      build_detection("gaze_net", "gaze_sustained_detected", {{"target_id", "alice"}}));
  auto second = tracker.associate_batch(second_batch, 30.2);
  assert(second.size() == 1);
  const auto second_track_id = second[0].second.payload.at("track_id");
  assert(second_track_id == first_track_id);

  std::vector<std::pair<std::string, robot_life_cpp::common::DetectionResult>> third_batch{};
  third_batch.emplace_back("motion", build_detection("motion_diff", "motion_detected", {}));
  auto third = tracker.associate_batch(third_batch, 30.3);
  assert(third.size() == 1);
  assert(third[0].second.payload.at("track_kind") == "object");
}

void test_resource_manager_preemption_and_release() {
  robot_life_cpp::behavior::ResourceManager resources{};
  auto first = resources.request_grant(
      "trace-1",
      "decision-1",
      "perform_attention",
      {"AudioOut"},
      {},
      1,
      5000,
      50.0);
  assert(first.granted);
  auto second = resources.request_grant(
      "trace-2",
      "decision-2",
      "perform_safety_alert",
      {"AudioOut"},
      {},
      3,
      5000,
      50.1);
  assert(second.granted);
  auto status = resources.get_resource_status(50.2);
  assert(status.at("AudioOut").find("perform_safety_alert") != std::string::npos);
  resources.release_grant(second.grant_id);
  auto status_after = resources.get_resource_status(50.3);
  assert(status_after.at("AudioOut") == "free");
}

void test_behavior_safety_guard_blocks_conflict_without_interrupt() {
  robot_life_cpp::behavior::BehaviorSafetyGuard guard{};

  auto current = build_decision(
      "perform_attention",
      robot_life_cpp::common::EventPriority::P1,
      robot_life_cpp::common::DecisionMode::Execute);
  auto incoming = build_decision(
      "perform_greeting",
      robot_life_cpp::common::EventPriority::P1,
      robot_life_cpp::common::DecisionMode::Execute);

  auto outcome = guard.evaluate(incoming, current);
  assert(!outcome.allowed);
  assert(outcome.reason.find("mutex_conflict_requires_interrupt") != std::string::npos);

  incoming.mode = robot_life_cpp::common::DecisionMode::SoftInterrupt;
  auto allowed = guard.evaluate(incoming, current);
  assert(allowed.allowed);
}

void test_behavior_executor_degrade_and_resume_queue() {
  robot_life_cpp::behavior::BehaviorExecutor executor{};

  auto active = build_decision(
      "perform_attention",
      robot_life_cpp::common::EventPriority::P1,
      robot_life_cpp::common::DecisionMode::Execute);
  active.required_resources = {"HeadMotion"};
  auto first_exec = executor.execute(active, 2000, 80.0);
  assert(first_exec.status == "finished");

  auto interrupting = build_decision(
      "perform_safety_alert",
      robot_life_cpp::common::EventPriority::P0,
      robot_life_cpp::common::DecisionMode::HardInterrupt);
  interrupting.required_resources = {"AudioOut"};
  interrupting.degraded_behavior = std::string{"safety_visual_only"};
  auto second_exec = executor.execute(interrupting, 2000, 80.1);
  assert(second_exec.status == "finished" || second_exec.status == "degraded");

  auto resumed = executor.pop_resume_decision();
  assert(resumed.has_value());
  assert(resumed->mode == robot_life_cpp::common::DecisionMode::Execute);
  assert(resumed->target_behavior == "perform_attention");
}

void test_runtime_execution_manager_history() {
  robot_life_cpp::runtime::ExecutionManager manager{};
  auto decision = build_decision(
      "perform_tracking",
      robot_life_cpp::common::EventPriority::P2,
      robot_life_cpp::common::DecisionMode::Execute);
  decision.required_resources = {"HeadMotion"};
  auto execution = manager.dispatch_decision(decision, 1500, 120.0);
  assert(execution.status == "finished");
  assert(!manager.history().empty());
  auto resumed = manager.drain_resume_decisions();
  assert(resumed.empty());
}

void test_runtime_telemetry_aggregates_stage_metrics() {
  robot_life_cpp::runtime::AggregatingTelemetrySink sink{};
  auto first = robot_life_cpp::runtime::emit_stage_trace(
      &sink,
      "trace-1",
      "arbitration",
      "ok",
      {{"outcome", "executed"}},
      10.0,
      10.01);
  auto second = robot_life_cpp::runtime::emit_stage_trace(
      &sink,
      "trace-2",
      "arbitration",
      "queued",
      {{"outcome", "queued"}},
      10.1,
      10.12);
  assert(first.duration_ms().has_value());
  assert(second.duration_ms().has_value());
  auto stats = sink.snapshot();
  assert(stats.contains("arbitration"));
  const auto& aggregate = stats.at("arbitration");
  assert(aggregate.count == 2);
  assert(aggregate.statuses.at("ok") == 1);
  assert(aggregate.statuses.at("queued") == 1);
  assert(aggregate.avg_duration_ms.has_value());
}

void test_runtime_life_state_snapshot_flags() {
  std::vector<robot_life_cpp::common::StableEvent> stable_events{};
  auto face = build_stable_event("familiar_face_detected", "user-a", 300.0);
  face.priority = robot_life_cpp::common::EventPriority::P1;
  stable_events.push_back(face);
  auto gaze = build_stable_event("gaze_hold_start_detected", "user-a", 300.1);
  stable_events.push_back(gaze);
  auto wave = build_stable_event("wave_detected", "user-a", 300.2);
  wave.priority = robot_life_cpp::common::EventPriority::P0;
  stable_events.push_back(wave);

  std::vector<robot_life_cpp::common::SceneCandidate> scenes{};
  auto latest_scene = build_scene("attention_scene", 0.9, 301.0, "user-a");
  latest_scene.payload["interaction_state"] = "engaging";
  latest_scene.payload["scene_path"] = "notice->attention";
  latest_scene.payload["engagement_score"] = "0.88";
  scenes.push_back(latest_scene);

  std::vector<robot_life_cpp::common::ExecutionResult> executions{};
  robot_life_cpp::common::ExecutionResult exec{};
  exec.execution_id = robot_life_cpp::common::new_id();
  exec.trace_id = robot_life_cpp::common::new_id();
  exec.behavior_id = "perform_attention";
  exec.status = "finished";
  exec.started_at = 300.0;
  exec.ended_at = 300.2;
  executions.push_back(exec);

  auto snapshot = robot_life_cpp::runtime::build_life_state_snapshot(stable_events, scenes, executions);
  assert(snapshot.latest_scene.has_value());
  assert(snapshot.latest_interaction_state == "engaging");
  assert(snapshot.latest_scene_path == "notice->attention");
  assert(snapshot.has_notice_signal);
  assert(snapshot.has_mutual_attention_signal);
  assert(snapshot.has_engagement_scene);
  assert(snapshot.has_p0_event);
  assert(snapshot.social_execution.has_value());
  assert(snapshot.latest_engagement_score.has_value());
}

void test_runtime_life_state_uses_configured_taxonomy_groups() {
  std::vector<robot_life_cpp::common::StableEvent> stable_events{};
  auto notice = build_stable_event("custom_notice_event", "user-b", 300.0);
  stable_events.push_back(notice);

  std::vector<robot_life_cpp::common::SceneCandidate> scenes{};
  scenes.push_back(build_scene("custom_attention_scene", 0.8, 301.0, "user-b"));

  robot_life_cpp::common::SceneTaxonomyRules taxonomy{};
  taxonomy.attention_scenes = {"custom_attention_scene"};
  taxonomy.noticed_scenes = {"custom_attention_scene"};
  taxonomy.notice_events = {"custom_notice_event"};

  auto snapshot = robot_life_cpp::runtime::build_life_state_snapshot(stable_events, scenes, {}, taxonomy);
  assert(snapshot.has_notice_signal);
  assert(snapshot.has_mutual_attention_signal);
}

void test_runtime_execution_support_finalize_and_resume_enqueue() {
  std::vector<robot_life_cpp::common::ExecutionResult> results{};
  robot_life_cpp::common::ExecutionResult execution{};
  execution.execution_id = robot_life_cpp::common::new_id();
  execution.trace_id = "trace-finalize";
  execution.behavior_id = "perform_tracking";
  execution.status = "finished";
  execution.started_at = 1.0;
  execution.ended_at = 1.2;

  robot_life_cpp::runtime::AggregatingTelemetrySink sink{};
  robot_life_cpp::runtime::finalize_execution(
      &results,
      execution,
      &sink,
      "behavior_executor",
      1.0,
      1.2,
      false,
      false);
  assert(results.size() == 1);
  auto stage_stats = sink.snapshot();
  assert(stage_stats.contains("behavior_executor"));

  robot_life_cpp::event_engine::ArbitratorRules rules{};
  rules.decision_cooldown_s = 0.0;
  robot_life_cpp::event_engine::ArbitrationRuntime arbitration_runtime{
      robot_life_cpp::event_engine::Arbitrator{rules},
      robot_life_cpp::event_engine::DecisionQueue{},
      40,
      2,
      2,
      1000};

  auto resumed = build_decision(
      "perform_attention",
      robot_life_cpp::common::EventPriority::P2,
      robot_life_cpp::common::DecisionMode::Execute);
  const bool enqueued = robot_life_cpp::runtime::enqueue_resumed_decision(
      &arbitration_runtime,
      &sink,
      resumed,
      2.0);
  assert(enqueued);
  assert(arbitration_runtime.pending(2.1) >= 1);
}

void test_profile_registry_parses_default_profile_and_names() {
  const auto temp_dir = std::filesystem::temp_directory_path();
  const auto catalog_path =
      temp_dir / ("robot_life_cpp_profile_catalog_" + robot_life_cpp::common::new_id() + ".yaml");

  {
    std::ofstream out(catalog_path);
    assert(out.good());
    out << "version: 2\n";
    out << "default_profile: mac_debug_native\n";
    out << "\n";
    out << "profiles:\n";
    out << "  mac_debug_native:\n";
    out << "    description: native\n";
    out << "  linux_deepstream_4vision:\n";
    out << "    description: ds\n";
  }

  robot_life_cpp::runtime::ProfileRegistry registry{catalog_path.string()};
  assert(registry.load());
  assert(registry.default_profile() == "mac_debug_native");
  assert(registry.has_profile("mac_debug_native"));
  assert(registry.has_profile("linux_deepstream_4vision"));
  assert(!registry.has_profile("missing_profile"));

  std::filesystem::remove(catalog_path);
}

void test_visual_contract_validates_detection_payloads() {
  auto detection = build_detection(
      "deepstream_face",
      std::string(robot_life_cpp::common::visual_contract::EVENT_FACE_DETECTED),
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "42"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_TRACK_ID), "person_track_1"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,100,120"},
      });

  const auto valid = robot_life_cpp::common::visual_contract::validate_visual_detection(detection);
  assert(valid.ok);

  detection.payload.erase(std::string(robot_life_cpp::common::visual_contract::KEY_BBOX));
  const auto invalid = robot_life_cpp::common::visual_contract::validate_visual_detection(detection);
  assert(!invalid.ok);
  assert(!invalid.missing_required_keys.empty());
}

void test_pipeline_factory_selects_backend_by_profile() {
  robot_life_cpp::runtime::PipelineFactory factory{};

  std::string error{};
  auto deepstream = factory.create_for_profile("linux_deepstream_4vision", &error);
  assert(deepstream != nullptr);
  assert(deepstream->backend_id() == "deepstream");

  auto native = factory.create_for_profile("mac_debug_native", &error);
  assert(native != nullptr);
  assert(native->backend_id() == "native");

  auto alias_deepstream = factory.create_for_profile("deepstream_prod", &error);
  assert(alias_deepstream != nullptr);
  assert(alias_deepstream->backend_id() == "deepstream");

  auto alias_native = factory.create_for_profile("cpu_debug", &error);
  assert(alias_native != nullptr);
  assert(alias_native->backend_id() == "native");

  auto missing = factory.create_for_profile("missing_profile", &error);
  assert(missing == nullptr);
  assert(error.find("unsupported profile") != std::string::npos);
}

void test_runtime_tuning_profile_loads_single_source_values() {
  const auto temp_dir = std::filesystem::temp_directory_path();
  const auto config_path =
      temp_dir / ("robot_life_cpp_runtime_tuning_" + robot_life_cpp::common::new_id() + ".yaml");
  {
    std::ofstream out(config_path);
    assert(out.good());
    out << "profiles.mac_debug_native.live_loop.tick_hz: 24\n";
    out << "profiles.mac_debug_native.live_loop.max_pending_events: 512\n";
    out << "profiles.mac_debug_native.event_injector.max_events_per_batch: 48\n";
    out << "profiles.mac_debug_native.stabilizer.debounce_count: 3\n";
    out << "profiles.mac_debug_native.aggregator.scene_bias.gesture_interaction: 1.4\n";
    out << "profiles.mac_debug_native.arbitrator.scene_priority.motion_alert: P1\n";
    out << "profiles.mac_debug_native.arbitrator.behavior_by_scene.motion_alert: track_motion\n";
    out << "profiles.mac_debug_native.taxonomy.default_scene: custom_default_scene\n";
    out << "profiles.mac_debug_native.taxonomy.proactive_scenes: custom_attention_scene,custom_greeting_scene\n";
    out << "profiles.mac_debug_native.taxonomy.event_scene_exact.wave_detected: custom_wave_scene\n";
    out << "profiles.mac_debug_native.taxonomy.event_scene_token.face: custom_presence_scene\n";
    out << "profiles.mac_debug_native.deepstream.face.sample_interval_frames: 4\n";
    out << "profiles.mac_debug_native.deepstream.motion.enabled: false\n";
  }

  robot_life_cpp::runtime::RuntimeTuningProfile tuning{};
  std::string error{};
  assert(robot_life_cpp::runtime::load_runtime_tuning_profile(
      config_path, "cpu_debug", &tuning, &error));
  assert(tuning.profile_name == "mac_debug_native");
  assert(tuning.live_loop.tick_hz == 24.0);
  assert(tuning.live_loop.max_pending_events == 512);
  assert(tuning.event_injector.max_events_per_batch == 48);
  assert(tuning.stabilizer.debounce_count == 3);
  assert(tuning.aggregator.scene_bias.at("gesture_interaction") == 1.4);
  assert(tuning.arbitrator.scene_priority.at("motion_alert") == robot_life_cpp::common::EventPriority::P1);
  assert(tuning.arbitrator.behavior_by_scene.at("motion_alert") == "track_motion");
  assert(tuning.taxonomy.default_scene == "custom_default_scene");
  assert(tuning.taxonomy.proactive_scenes.contains("custom_attention_scene"));
  assert(tuning.taxonomy.event_scene_exact.at("wave_detected") == "custom_wave_scene");
  assert(tuning.taxonomy.event_scene_token.at("face") == "custom_presence_scene");
  assert(tuning.aggregator.taxonomy.default_scene == "custom_default_scene");
  assert(tuning.branch_intervals.at(robot_life_cpp::perception::DeepStreamBranchId::Face) == 4);
  assert(!tuning.branch_enabled.at(robot_life_cpp::perception::DeepStreamBranchId::Motion));

  std::filesystem::remove(config_path);
}

void test_runtime_tuning_store_reloads_after_file_change() {
  const auto temp_dir = std::filesystem::temp_directory_path();
  const auto config_path =
      temp_dir / ("robot_life_cpp_runtime_tuning_reload_" + robot_life_cpp::common::new_id() + ".yaml");
  {
    std::ofstream out(config_path);
    assert(out.good());
    out << "profiles.mac_debug_native.live_loop.tick_hz: 20\n";
  }

  robot_life_cpp::runtime::RuntimeTuningStore store{config_path};
  std::string error{};
  assert(store.load("mac_debug_native", &error));
  assert(store.current().has_value());
  assert(store.current()->live_loop.tick_hz == 20.0);

  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  {
    std::ofstream out(config_path);
    assert(out.good());
    out << "profiles.mac_debug_native.live_loop.tick_hz: 26\n";
  }

  bool reloaded = false;
  assert(store.reload_if_changed("mac_debug_native", &reloaded, &error));
  assert(reloaded);
  assert(store.current().has_value());
  assert(store.current()->live_loop.tick_hz == 26.0);

  std::filesystem::remove(config_path);
}

void test_runtime_tuning_applies_to_graph_config() {
  robot_life_cpp::runtime::RuntimeTuningProfile tuning{};
  tuning.share_preprocess = false;
  tuning.share_tracker = false;
  tuning.max_detections_per_frame = 2;
  tuning.branch_enabled[robot_life_cpp::perception::DeepStreamBranchId::Face] = true;
  tuning.branch_enabled[robot_life_cpp::perception::DeepStreamBranchId::Motion] = false;
  tuning.branch_intervals[robot_life_cpp::perception::DeepStreamBranchId::PoseGesture] = 5;

  auto graph_config = robot_life_cpp::perception::default_deepstream_graph_config();
  robot_life_cpp::runtime::apply_runtime_tuning_to_graph(tuning, &graph_config);

  assert(!graph_config.share_preprocess);
  assert(!graph_config.share_tracker);
  assert(graph_config.max_detections_per_frame == 2);
  assert(graph_config.branches[0].enabled);
  assert(!graph_config.branches[2].enabled);
  assert(graph_config.branches[1].sample_interval_frames == 5);
}

void test_scene_aggregator_uses_configured_taxonomy_mapping() {
  robot_life_cpp::event_engine::SceneAggregatorRules rules{};
  rules.taxonomy.default_scene = "custom_default_scene";
  rules.taxonomy.event_scene_exact["custom_signal"] = "custom_scene";
  robot_life_cpp::event_engine::SceneAggregator aggregator{rules};

  std::vector<robot_life_cpp::common::StableEvent> stable_events{};
  auto event = build_stable_event("custom_signal", "user-x", 40.0);
  event.payload["confidence"] = "0.75";
  stable_events.push_back(event);

  const auto scenes = aggregator.update(stable_events, 10.0);
  assert(!scenes.empty());
  assert(scenes.front().scene_type == "custom_scene");
}

void test_load_shedder_reduces_preview_and_batch_under_pressure() {
  robot_life_cpp::runtime::RuntimeLoadShedder shedder{};
  robot_life_cpp::runtime::LoadShedderInput input{};
  input.ui_enabled = true;
  input.configured_max_events_per_batch = 96;
  input.runtime.pending_events = 256;
  input.runtime.scene_candidates_last_tick = 9;
  input.backend.backend_id = "deepstream";
  input.backend.delivered_batches = 10;
  input.backend.delivered_detections = 80;

  const auto decision = shedder.decide(input);
  assert(decision.pressure == robot_life_cpp::runtime::LoadPressure::Shed);
  assert(decision.max_events_per_batch <= 16);
  assert(decision.preview_every_ticks >= 4);
  assert(decision.telemetry_every_ticks >= 4);
}

void test_load_shedder_preserves_configured_batch_cap_when_normal() {
  robot_life_cpp::runtime::RuntimeLoadShedder shedder{};
  robot_life_cpp::runtime::LoadShedderInput input{};
  input.ui_enabled = true;
  input.configured_max_events_per_batch = 96;

  const auto decision = shedder.decide(input);
  assert(decision.pressure == robot_life_cpp::runtime::LoadPressure::Normal);
  assert(decision.max_events_per_batch == 96);
}

void test_debug_dashboard_renderers_include_runtime_and_load_information() {
  robot_life_cpp::runtime::DebugDashboardData data{};
  data.runtime.pending_events = 12;
  data.runtime.scene_candidates_last_tick = 3;
  data.backend.backend_id = "native";
  data.backend.delivered_batches = 5;
  data.backend.delivered_detections = 12;
  data.load_shed.pressure = robot_life_cpp::runtime::LoadPressure::Warning;
  data.load_shed.reason = "elevated_load";
  data.platform = "macos";
  data.gpu_summary = "Built without CUDA toolkit";
  data.health.phase = robot_life_cpp::runtime::RuntimePhase::Ready;
  data.health.detail = "backend and core ready";
  data.tuning.branch_enabled[robot_life_cpp::perception::DeepStreamBranchId::Face] = true;
  data.tuning.branch_intervals[robot_life_cpp::perception::DeepStreamBranchId::Face] = 1;
  data.preview_detections.push_back(build_detection(
      "deepstream_face",
      "face_detected",
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CLASS_NAME), "face"},
      }));

  const auto json = robot_life_cpp::runtime::render_debug_dashboard_json(data);
  const auto html = robot_life_cpp::runtime::render_debug_dashboard_html(data);
  assert(json.find("\"load_shed\"") != std::string::npos);
  assert(json.find("\"platform\":\"macos\"") != std::string::npos);
  assert(json.find("\"phase\":\"ready\"") != std::string::npos);
  assert(json.find("\"detail\":\"backend and core ready\"") != std::string::npos);
  assert(html.find("Robot Life Debug UI") != std::string::npos);
  assert(html.find("elevated_load") != std::string::npos);
}

void test_deepstream_protocol_roundtrip() {
  robot_life_cpp::common::DetectionResult detection{};
  detection.trace_id = "trace-1";
  detection.source = "front_cam";
  detection.detector = "deepstream_face";
  detection.event_type = std::string(robot_life_cpp::common::visual_contract::EVENT_FACE_DETECTED);
  detection.timestamp = 12.5;
  detection.confidence = 0.91;
  detection.payload = {
      {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
      {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "3"},
      {std::string(robot_life_cpp::common::visual_contract::KEY_TRACK_ID), "person_track_1"},
      {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,30,40"},
  };

  const auto encoded = robot_life_cpp::bridge::encode_detection_line(detection);
  const auto decoded = robot_life_cpp::bridge::parse_deepstream_line(encoded);
  assert(decoded.has_value());
  assert(decoded->kind == robot_life_cpp::bridge::DeepStreamEnvelope::Kind::Detection);
  assert(decoded->detection.has_value());
  assert(decoded->detection->event_type == detection.event_type);
  assert(decoded->detection->payload.at("track_id") == "person_track_1");
}

void test_deepstream_process_backend_streams_mock_detections() {
  robot_life_cpp::runtime::PipelineFactory factory{};
  std::string error{};
  auto deepstream = factory.create_for_profile("linux_deepstream_4vision", &error);
  assert(deepstream != nullptr);
  assert(deepstream->start());

  std::vector<robot_life_cpp::common::DetectionResult> detections{};
  for (int i = 0; i < 20 && detections.empty(); ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    detections = deepstream->poll(8);
  }

  assert(!detections.empty());
  const auto health = deepstream->health();
  assert(health.healthy);
  assert(health.state == "ready" || health.state == "warming" || health.state == "starting");
  deepstream->stop();
}

void test_deepstream_launch_spec_prefers_mock_on_non_linux_real_request() {
  const auto temp_dir = std::filesystem::temp_directory_path();
  const auto config_path =
      temp_dir / ("robot_life_cpp_deepstream_launch_" + robot_life_cpp::common::new_id() + ".yaml");
  {
    std::ofstream out(config_path);
    assert(out.good());
    out << "graph_name: launch_spec_test\n";
  }

  ScopedEnvVar mode{"ROBOT_LIFE_CPP_DEEPSTREAM_MODE", "real"};
  ScopedEnvVar graph_config{"ROBOT_LIFE_CPP_DEEPSTREAM_GRAPH_CONFIG", config_path.string()};
  ScopedEnvVar deepstream_app{"DEEPSTREAM_APP", "/bin/echo"};
  ScopedEnvVar metadata_path{"ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH",
                             (temp_dir / "metadata.ndjson").string()};
  ScopedEnvVar app_config_path{"ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH",
                               (temp_dir / "generated_app.txt").string()};
  const auto spec = robot_life_cpp::perception::resolve_deepstream_launch_spec();
  assert(spec.requested_mode == "real");
#if defined(__linux__)
  assert(spec.resolved_mode == "real");
  assert(spec.real_runtime_available);
#else
  assert(spec.resolved_mode == "mock");
  assert(!spec.real_runtime_available);
  assert(spec.detail.find("host_not_linux") != std::string::npos);
#endif
  assert(spec.command.find("deepstream-backend") != std::string::npos);
  assert(spec.command.find("--metadata-path") != std::string::npos);
  assert(spec.command.find("--write-app-config") != std::string::npos);
  assert(spec.metadata_path == temp_dir / "metadata.ndjson");
  assert(spec.generated_app_config_path == temp_dir / "generated_app.txt");
  std::filesystem::remove(config_path);
}

void test_deepstream_launch_spec_honors_explicit_mock_mode() {
  ScopedEnvVar mode{"ROBOT_LIFE_CPP_DEEPSTREAM_MODE", "mock"};
  const auto spec = robot_life_cpp::perception::resolve_deepstream_launch_spec();
  assert(spec.requested_mode == "mock");
  assert(spec.resolved_mode == "mock");
  assert(spec.detail == "requested mock mode");
  assert(spec.command.find("--mode mock") != std::string::npos);
}

void test_deepstream_runner_factory_selects_real_and_mock() {
  auto mock_runner = robot_life_cpp::perception::make_deepstream_runner("mock");
  assert(mock_runner != nullptr);
  assert(mock_runner->runner_id() == "mock");

  auto real_runner = robot_life_cpp::perception::make_deepstream_runner("real");
  assert(real_runner != nullptr);
  assert(real_runner->runner_id() == "real");

  auto auto_runner = robot_life_cpp::perception::make_deepstream_runner("auto");
  assert(auto_runner != nullptr);
  assert(auto_runner->runner_id() == "mock");
}

void test_deepstream_adapter_normalizes_and_deduplicates() {
  robot_life_cpp::perception::DeepStreamAdapter adapter{};

  robot_life_cpp::common::DetectionResult raw{};
  raw.source = "front_cam";
  raw.detector = "deepstream_face";
  raw.event_type = "face";
  raw.confidence = 0.95;
  raw.payload = {
      {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,30,40"},
  };

  robot_life_cpp::bridge::DeepStreamEnvelope envelope{};
  envelope.kind = robot_life_cpp::bridge::DeepStreamEnvelope::Kind::Detection;
  envelope.detection = raw;

  const auto adapted = adapter.adapt_detection(envelope);
  assert(adapted.has_value());
  assert(adapted->event_type == "face_detected");
  assert(adapted->payload.contains("camera_id"));
  assert(adapted->payload.contains("frame_id"));
  assert(adapted->payload.contains("track_id"));
  assert(adapted->payload.contains("exporter_version"));

  const auto duplicate = adapter.adapt_detection(envelope);
  assert(!duplicate.has_value());
}

void test_deepstream_export_contract_validates_required_keys() {
  std::vector<std::string> keys = {
      "camera_id",
      "frame_id",
      "track_id",
      "bbox",
      "branch_id",
      "branch_name",
      "plugin",
      "binding_stage",
      "device",
      "track_kind",
      "exporter_version",
  };
  std::vector<std::string> missing{};
  assert(robot_life_cpp::perception::deepstream_export_contract::validate_export_payload_keys(keys, &missing));
  assert(missing.empty());

  keys.pop_back();
  assert(!robot_life_cpp::perception::deepstream_export_contract::validate_export_payload_keys(keys, &missing));
}

void test_deepstream_exporter_exports_protocol_lines_consumed_by_adapter() {
  robot_life_cpp::perception::DeepStreamFrameMetadata frame{};
  frame.source = "front_cam";
  frame.camera_id = "front_cam";
  frame.frame_id = "42";
  frame.timestamp = 12.5;

  robot_life_cpp::perception::DeepStreamObjectMetadata object{};
  object.branch_id = "face";
  object.branch_name = "face";
  object.detector = "deepstream_face";
  object.event_type = "face";
  object.plugin = "nvinfer";
  object.binding_stage = "detect_track_embed";
  object.device = "cuda:0";
  object.track_kind = "face";
  object.track_id = "face_track_42";
  object.bbox = "10,20,100,120";
  object.confidence = 0.94;
  object.class_name = std::string{"person"};
  object.embedding_ref = std::string{"face_embedding_42"};
  frame.objects.push_back(object);

  robot_life_cpp::perception::DeepStreamExporter exporter{};
  const auto lines = exporter.export_frame_lines(frame);
  assert(lines.size() == 1);

  const auto envelope = robot_life_cpp::bridge::parse_deepstream_line(lines.front());
  assert(envelope.has_value());
  assert(envelope->kind == robot_life_cpp::bridge::DeepStreamEnvelope::Kind::Detection);

  robot_life_cpp::perception::DeepStreamAdapter adapter{};
  const auto adapted = adapter.adapt_detection(*envelope);
  assert(adapted.has_value());
  assert(adapted->event_type == "face_detected");
  assert(adapted->payload.at("branch_id") == "face");
  assert(adapted->payload.at("plugin") == "nvinfer");
  assert(adapted->payload.at("embedding_ref") == "face_embedding_42");
  assert(adapted->payload.at("exporter_version") == "deepstream-export-contract/v1");
}

void test_deepstream_exporter_skips_empty_frame_and_missing_required_fields() {
  robot_life_cpp::perception::DeepStreamExporter exporter{};

  robot_life_cpp::perception::DeepStreamFrameMetadata empty_frame{};
  empty_frame.camera_id = "front_cam";
  empty_frame.frame_id = "100";
  assert(exporter.export_frame_lines(empty_frame).empty());

  robot_life_cpp::perception::DeepStreamFrameMetadata invalid_frame{};
  invalid_frame.camera_id = "front_cam";
  invalid_frame.frame_id = "101";

  robot_life_cpp::perception::DeepStreamObjectMetadata invalid_object{};
  invalid_object.branch_id = "face";
  invalid_object.branch_name = "face";
  invalid_object.plugin = "nvinfer";
  invalid_object.binding_stage = "detect_track_embed";
  invalid_object.device = "cuda:0";
  invalid_object.track_kind = "face";
  invalid_object.track_id = "face_track_missing_bbox";
  invalid_object.event_type = "face";
  invalid_frame.objects.push_back(invalid_object);

  assert(exporter.export_frame_lines(invalid_frame).empty());
}

void test_deepstream_exporter_rejects_malformed_bbox_and_deduplicates_frame_objects() {
  robot_life_cpp::perception::DeepStreamExporter exporter{};

  robot_life_cpp::perception::DeepStreamFrameMetadata frame{};
  frame.camera_id = "front_cam";
  frame.frame_id = "200";
  frame.source = "front_cam";

  robot_life_cpp::perception::DeepStreamObjectMetadata malformed{};
  malformed.branch_id = "motion";
  malformed.branch_name = "motion";
  malformed.detector = "deepstream_motion";
  malformed.event_type = "motion";
  malformed.plugin = "custom_motion";
  malformed.binding_stage = "frame_delta_motion";
  malformed.device = "cuda:0";
  malformed.track_kind = "motion";
  malformed.track_id = "motion_track_1";
  malformed.bbox = "10,20,30";
  malformed.confidence = 0.8;
  frame.objects.push_back(malformed);

  robot_life_cpp::perception::DeepStreamObjectMetadata valid{};
  valid.branch_id = "scene_object";
  valid.branch_name = "scene_object";
  valid.detector = "deepstream_scene";
  valid.event_type = "scene_context_detected";
  valid.plugin = "nvinfer";
  valid.binding_stage = "detect_scene_context";
  valid.device = "cuda:0";
  valid.track_kind = "scene";
  valid.track_id = "scene_track_1";
  valid.bbox = "10,20,30,40";
  valid.confidence = 0.88;
  valid.scene_tags = std::string{"person,desk"};
  frame.objects.push_back(valid);
  frame.objects.push_back(valid);

  const auto lines = exporter.export_frame_lines(frame);
  assert(lines.size() == 1);
  const auto envelope = robot_life_cpp::bridge::parse_deepstream_line(lines.front());
  assert(envelope.has_value());
  assert(envelope->detection.has_value());
  assert(envelope->detection->payload.at("scene_tags") == "person,desk");
}

void test_deepstream_exporter_allows_partial_optional_payloads() {
  robot_life_cpp::perception::DeepStreamExporter exporter{};

  robot_life_cpp::perception::DeepStreamFrameMetadata frame{};
  frame.camera_id = "front_cam";
  frame.frame_id = "300";

  robot_life_cpp::perception::DeepStreamObjectMetadata object{};
  object.branch_id = "pose_gesture";
  object.branch_name = "pose_gesture";
  object.detector = "deepstream_pose";
  object.event_type = "pose_detected";
  object.plugin = "nvinfer";
  object.binding_stage = "detect_keypoints_gesture";
  object.device = "cuda:0";
  object.track_kind = "person";
  object.track_id = "person_track_300";
  object.bbox = "11,22,33,44";
  object.confidence = 0.92;
  frame.objects.push_back(object);

  const auto lines = exporter.export_frame_lines(frame);
  assert(lines.size() == 1);
  const auto envelope = robot_life_cpp::bridge::parse_deepstream_line(lines.front());
  assert(envelope.has_value());
  assert(envelope->detection.has_value());
  assert(!envelope->detection->payload.contains("landmarks"));
  assert(envelope->detection->payload.at("binding_stage") == "detect_keypoints_gesture");
}

void test_deepstream_graph_emits_four_branches_and_tracks_stats() {
  robot_life_cpp::perception::DeepStreamFourVisionGraph graph{};

  auto detections = graph.ingest_frame("front_cam", 0);
  assert(detections.size() == 4);
  for (const auto& detection : detections) {
    assert(detection.payload.contains("branch_id"));
    assert(detection.payload.contains("branch_name"));
    assert(detection.payload.contains("track_kind"));
    assert(detection.payload.contains("shared_preprocess_seq"));
    assert(detection.payload.contains("shared_tracker_seq"));
    assert(detection.payload.contains("plugin"));
    assert(detection.payload.contains("model_config_path"));
    assert(detection.payload.contains("binding_stage"));
    assert(detection.payload.contains("device"));
  }

  auto stats = graph.stats();
  assert(stats.frames_ingested == 1);
  assert(stats.shared_preprocess_runs == 1);
  assert(stats.shared_tracker_updates == 1);
  assert(stats.detections_emitted == 4);
  assert(stats.enabled_branch_count == 4);
  assert(stats.branches.size() == 4);
}

void test_deepstream_graph_branch_toggle_and_sampling() {
  robot_life_cpp::perception::DeepStreamFourVisionGraph graph{};
  assert(graph.set_branch_enabled(robot_life_cpp::perception::DeepStreamBranchId::Motion, false));
  assert(graph.set_branch_interval(robot_life_cpp::perception::DeepStreamBranchId::SceneObject, 2));

  auto first = graph.ingest_frame("front_cam", 1);
  for (const auto& detection : first) {
    assert(detection.detector != "deepstream_motion");
    assert(detection.detector != "deepstream_scene");
  }

  auto second = graph.ingest_frame("front_cam", 2);
  bool scene_seen = false;
  for (const auto& detection : second) {
    if (detection.detector == "deepstream_scene") {
      scene_seen = true;
    }
    assert(detection.detector != "deepstream_motion");
  }
  assert(scene_seen);

  const auto stats = graph.stats();
  assert(stats.disabled_branch_hits >= 1);
  assert(stats.sampled_branch_hits >= 1);
  assert(stats.branches.size() == 4);
  const auto& motion_stats = stats.branches[2];
  assert(motion_stats.frames_skipped_disabled >= 2);
  const auto& scene_stats = stats.branches[3];
  assert(scene_stats.frames_skipped_sampling >= 1);
}

void test_deepstream_graph_configures_shared_stages_and_output_cap() {
  robot_life_cpp::perception::DeepStreamFourVisionGraph graph{};
  assert(graph.set_share_preprocess(false));
  assert(graph.set_share_tracker(false));
  assert(graph.set_max_detections_per_frame(2));

  const auto detections = graph.ingest_frame("front_cam", 0);
  assert(detections.size() == 2);

  const auto stats = graph.stats();
  assert(stats.shared_preprocess_runs == 0);
  assert(stats.shared_tracker_updates == 0);
  assert(stats.detections_dropped_due_to_cap >= 1);
  assert(stats.enabled_branch_count == 4);
}

void test_deepstream_graph_loads_external_binding_config() {
  const auto temp_dir = std::filesystem::temp_directory_path();
  const auto config_path =
      temp_dir / ("robot_life_cpp_deepstream_graph_" + robot_life_cpp::common::new_id() + ".yaml");

  {
    std::ofstream out(config_path);
    assert(out.good());
    out << "graph_name: custom_graph\n";
    out << "share_preprocess: false\n";
    out << "share_tracker: false\n";
    out << "max_detections_per_frame: 2\n";
    out << "branch.face.sample_interval_frames: 4\n";
    out << "branch.face.plugin: nvtracker\n";
    out << "branch.face.model_config_path: models/deepstream/face/custom.txt\n";
    out << "branch.face.binding_stage: custom_stage\n";
    out << "branch.face.device: cuda:1\n";
    out << "branch.motion.enabled: false\n";
  }

  robot_life_cpp::perception::DeepStreamGraphConfig config{};
  std::string error{};
  const bool loaded =
      robot_life_cpp::perception::load_deepstream_graph_config(config_path, &config, &error);
  assert(loaded);
  assert(error.empty());
  assert(config.graph_name == "custom_graph");
  assert(!config.share_preprocess);
  assert(!config.share_tracker);
  assert(config.max_detections_per_frame == 2);
  assert(config.branches.size() == 4);
  assert(config.branches[0].sample_interval_frames == 4);
  assert(config.branches[0].plugin == "nvtracker");
  assert(config.branches[0].model_config_path == "models/deepstream/face/custom.txt");
  assert(config.branches[0].binding_stage == "custom_stage");
  assert(config.branches[0].device == "cuda:1");
  assert(!config.branches[2].enabled);

  robot_life_cpp::perception::DeepStreamFourVisionGraph graph{config};
  const auto detections = graph.ingest_frame("front_cam", 4);
  assert(detections.size() == 1);
  assert(detections[0].detector == "deepstream_face");
  assert(detections[0].payload.at("plugin") == "nvtracker");

  std::filesystem::remove(config_path);
}

void test_deepstream_execution_plan_resolves_branch_assets_and_renders_app_config() {
  const auto temp_dir =
      std::filesystem::temp_directory_path() / ("robot_life_cpp_ds_plan_" + robot_life_cpp::common::new_id());
  std::filesystem::create_directories(temp_dir / "models/deepstream/face");
  std::filesystem::create_directories(temp_dir / "models/deepstream/pose");
  std::filesystem::create_directories(temp_dir / "models/deepstream/motion");
  std::filesystem::create_directories(temp_dir / "models/deepstream/scene");

  const auto face_cfg = temp_dir / "models/deepstream/face/pgie_face.txt";
  const auto pose_cfg = temp_dir / "models/deepstream/pose/pgie_pose.txt";
  const auto motion_cfg = temp_dir / "models/deepstream/motion/motion_config.txt";
  const auto scene_cfg = temp_dir / "models/deepstream/scene/pgie_scene.txt";
  {
    std::ofstream out(face_cfg);
    assert(out.good());
    out << "[property]\n";
    out << "network-type=detector\n";
    out << "labelfile-path=labels_face.txt\n";
    out << "model-engine-file=face.engine\n";
    out << "tracker-config-file=tracker_face.txt\n";
    out << "batch-size=1\n";
    out << "gpu-id=0\n";
  }
  {
    std::ofstream out(pose_cfg);
    assert(out.good());
    out << "[property]\n";
    out << "network-type=pose\n";
    out << "labelfile-path=labels_pose.txt\n";
    out << "model-engine-file=pose.engine\n";
    out << "batch-size=1\n";
    out << "gpu-id=0\n";
  }
  {
    std::ofstream out(motion_cfg);
    assert(out.good());
    out << "[property]\n";
    out << "network-type=custom-motion\n";
    out << "model-engine-file=motion.engine\n";
    out << "motion-threshold=0.35\n";
    out << "batch-size=1\n";
    out << "gpu-id=0\n";
  }
  {
    std::ofstream out(scene_cfg);
    assert(out.good());
    out << "[property]\n";
    out << "network-type=detector\n";
    out << "labelfile-path=labels_scene.txt\n";
    out << "model-engine-file=scene.engine\n";
    out << "group-classes=person,animal,other\n";
    out << "batch-size=1\n";
    out << "gpu-id=0\n";
  }

  const auto graph_cfg = temp_dir / "deepstream_4vision.yaml";
  {
    std::ofstream out(graph_cfg);
    assert(out.good());
    out << "graph_name: real_plan_test\n";
    out << "branch.face.model_config_path: models/deepstream/face/pgie_face.txt\n";
    out << "branch.pose_gesture.model_config_path: models/deepstream/pose/pgie_pose.txt\n";
    out << "branch.motion.model_config_path: models/deepstream/motion/motion_config.txt\n";
    out << "branch.scene_object.model_config_path: models/deepstream/scene/pgie_scene.txt\n";
  }

  robot_life_cpp::perception::DeepStreamGraphConfig config{};
  std::string error{};
  assert(robot_life_cpp::perception::load_deepstream_graph_config(graph_cfg, &config, &error));
  const auto plan = robot_life_cpp::perception::build_deepstream_execution_plan(config, graph_cfg);
  assert(robot_life_cpp::perception::deepstream_execution_plan_valid(plan));
  assert(plan.graph_name == "real_plan_test");
  assert(plan.branches.size() == 4);
  assert(plan.branches[0].model_config_exists);
  assert(plan.branches[0].model_config_path == face_cfg);
  assert(plan.branches[0].scene_hint == "human_presence");
  assert(plan.branches[0].missing_model_properties.empty());
  assert(std::find(plan.branches[0].allowed_event_types.begin(),
                   plan.branches[0].allowed_event_types.end(),
                   "face_identity_detected") != plan.branches[0].allowed_event_types.end());
  assert(plan.branches[1].scene_hint == "body_pose");
  assert(plan.branches[2].scene_hint == "motion_alert");
  assert(plan.branches[3].scene_hint == "generic_event");
  assert(!plan.branches[2].uses_shared_tracker);

  const auto rendered = robot_life_cpp::perception::render_deepstream_app_config(plan);
  assert(rendered.find("[application]") != std::string::npos);
  assert(rendered.find("[streammux]") != std::string::npos);
  assert(rendered.find("[branch-face]") != std::string::npos);
  assert(rendered.find(face_cfg.string()) != std::string::npos);

  std::filesystem::remove_all(temp_dir);
}

void test_deepstream_execution_plan_validates_branch_specific_model_properties() {
  const auto temp_dir =
      std::filesystem::temp_directory_path() / ("robot_life_cpp_ds_props_" + robot_life_cpp::common::new_id());
  std::filesystem::create_directories(temp_dir / "models/deepstream/face");
  {
    std::ofstream out(temp_dir / "models/deepstream/face/pgie_face.txt");
    assert(out.good());
    out << "[property]\n";
    out << "network-type=detector\n";
    out << "labelfile-path=labels_face.txt\n";
    out << "model-engine-file=face.engine\n";
    out << "batch-size=1\n";
    out << "gpu-id=0\n";
  }
  {
    std::ofstream out(temp_dir / "deepstream_4vision.yaml");
    assert(out.good());
    out << "branch.face.model_config_path: models/deepstream/face/pgie_face.txt\n";
    out << "branch.pose_gesture.enabled: false\n";
    out << "branch.motion.enabled: false\n";
    out << "branch.scene_object.enabled: false\n";
  }

  robot_life_cpp::perception::DeepStreamGraphConfig config{};
  std::string error{};
  assert(robot_life_cpp::perception::load_deepstream_graph_config(
      temp_dir / "deepstream_4vision.yaml", &config, &error));
  const auto plan = robot_life_cpp::perception::build_deepstream_execution_plan(
      config, temp_dir / "deepstream_4vision.yaml");
  assert(!robot_life_cpp::perception::deepstream_execution_plan_valid(plan));
  assert(std::find(plan.branches[0].missing_model_properties.begin(),
                   plan.branches[0].missing_model_properties.end(),
                   "tracker-config-file") != plan.branches[0].missing_model_properties.end());
  std::filesystem::remove_all(temp_dir);
}

void test_deepstream_branch_event_mapping_face_identity_and_attention() {
  robot_life_cpp::common::Payload identity_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_IDENTITY_STATE), "familiar"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::Face,
             identity_payload,
             "face_detected") == "face_identity_detected");

  robot_life_cpp::common::Payload attention_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_ATTENTION_STATE), "looking_at_camera"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::Face,
             attention_payload,
             "face_detected") == "face_attention_detected");
}

void test_deepstream_branch_event_mapping_pose_gesture_and_wave() {
  robot_life_cpp::common::Payload wave_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_GESTURE_NAME), "wave"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::PoseGesture,
             wave_payload,
             "pose_detected") == "wave_detected");

  robot_life_cpp::common::Payload gesture_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_GESTURE_NAME), "beckon"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::PoseGesture,
             gesture_payload,
             "pose_detected") == "gesture_detected");
}

void test_deepstream_branch_event_mapping_motion_direction() {
  robot_life_cpp::common::Payload approaching_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_MOTION_DIRECTION), "approaching"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::Motion,
             approaching_payload,
             "motion_detected") == "approaching_detected");

  robot_life_cpp::common::Payload leaving_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_MOTION_DIRECTION), "leaving"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::Motion,
             leaving_payload,
             "motion_detected") == "leaving_detected");
}

void test_deepstream_branch_event_mapping_scene_object_class() {
  robot_life_cpp::common::Payload person_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_CLASS_NAME), "person"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::SceneObject,
             person_payload,
             "scene_context_detected") == "person_present_detected");

  robot_life_cpp::common::Payload animal_payload{
      {std::string(robot_life_cpp::common::visual_contract::KEY_CLASS_NAME), "animal"},
  };
  assert(robot_life_cpp::perception::resolve_deepstream_branch_event_type(
             robot_life_cpp::perception::DeepStreamBranchId::SceneObject,
             animal_payload,
             "scene_context_detected") == "object_detected");
}

void test_deepstream_event_flow_face_end_to_end() {
  robot_life_cpp::perception::DeepStreamObjectMetadata object{};
  object.branch_id = "face";
  object.branch_name = "face";
  object.detector = "deepstream_face";
  object.event_type = "face_detected";
  object.plugin = "nvinfer";
  object.binding_stage = "detect_track_embed";
  object.device = "cuda:0";
  object.track_kind = "face";
  object.track_id = "face_track_1";
  object.bbox = "10,20,120,160";
  object.confidence = 0.96;
  object.class_name = "face";
  object.embedding_ref = "embedding_1";
  object.identity_state = "familiar";

  std::vector<robot_life_cpp::perception::DeepStreamFrameMetadata> frames{};
  frames.push_back(build_frame_metadata("10", object));
  frames.push_back(build_frame_metadata("11", object));

  std::vector<robot_life_cpp::common::RawEvent> events{};
  const auto decision = run_event_flow(frames, &events);
  assert(events.size() == 2);
  assert(events.front().event_type == "face_identity_detected");
  assert(decision.has_value());
  assert(decision->target_behavior == "engage_presence");
}

void test_deepstream_event_flow_pose_gesture_end_to_end() {
  robot_life_cpp::perception::DeepStreamObjectMetadata object{};
  object.branch_id = "pose_gesture";
  object.branch_name = "pose_gesture";
  object.detector = "deepstream_pose";
  object.event_type = "pose_detected";
  object.plugin = "nvinfer";
  object.binding_stage = "detect_keypoints_gesture";
  object.device = "cuda:0";
  object.track_kind = "person";
  object.track_id = "person_track_2";
  object.bbox = "12,24,140,180";
  object.confidence = 0.93;
  object.class_name = "person";
  object.landmarks = "nose:0.4,0.2";
  object.gesture_name = "wave";

  std::vector<robot_life_cpp::perception::DeepStreamFrameMetadata> frames{};
  frames.push_back(build_frame_metadata("20", object));
  frames.push_back(build_frame_metadata("21", object));

  std::vector<robot_life_cpp::common::RawEvent> events{};
  const auto decision = run_event_flow(frames, &events);
  assert(events.size() == 2);
  assert(events.front().event_type == "wave_detected");
  assert(decision.has_value());
  assert(decision->target_behavior == "interactive_gesture");
}

void test_deepstream_event_flow_motion_end_to_end() {
  robot_life_cpp::perception::DeepStreamObjectMetadata object{};
  object.branch_id = "motion";
  object.branch_name = "motion";
  object.detector = "deepstream_motion";
  object.event_type = "motion_detected";
  object.plugin = "custom_motion";
  object.binding_stage = "frame_delta_motion";
  object.device = "cuda:0";
  object.track_kind = "motion";
  object.track_id = "motion_track_3";
  object.bbox = "30,40,160,200";
  object.confidence = 0.84;
  object.motion_score = "0.81";
  object.motion_direction = "approaching";

  std::vector<robot_life_cpp::perception::DeepStreamFrameMetadata> frames{};
  frames.push_back(build_frame_metadata("30", object));
  frames.push_back(build_frame_metadata("31", object));

  std::vector<robot_life_cpp::common::RawEvent> events{};
  const auto decision = run_event_flow(frames, &events);
  assert(events.size() == 2);
  assert(events.front().event_type == "approaching_detected");
  assert(decision.has_value());
  assert(decision->target_behavior == "motion_observe");
}

void test_deepstream_event_flow_scene_object_end_to_end() {
  robot_life_cpp::perception::DeepStreamObjectMetadata object{};
  object.branch_id = "scene_object";
  object.branch_name = "scene_object";
  object.detector = "deepstream_scene";
  object.event_type = "scene_context_detected";
  object.plugin = "nvinfer";
  object.binding_stage = "detect_scene_context";
  object.device = "cuda:0";
  object.track_kind = "scene";
  object.track_id = "scene_track_4";
  object.bbox = "40,50,180,220";
  object.confidence = 0.88;
  object.class_name = "animal";
  object.scene_tags = "animal,pet";

  std::vector<robot_life_cpp::perception::DeepStreamFrameMetadata> frames{};
  frames.push_back(build_frame_metadata("40", object));
  frames.push_back(build_frame_metadata("41", object));

  std::vector<robot_life_cpp::common::RawEvent> events{};
  const auto decision = run_event_flow(frames, &events);
  assert(events.size() == 2);
  assert(events.front().event_type == "object_detected");
  assert(decision.has_value());
  assert(decision->target_behavior == "idle_scan");
}

void test_deepstream_execution_plan_reports_missing_model_configs() {
  auto config = robot_life_cpp::perception::default_deepstream_graph_config();
  config.branches[0].model_config_path = "missing_face.txt";
  const auto plan = robot_life_cpp::perception::build_deepstream_execution_plan(config, {});
  assert(!robot_life_cpp::perception::deepstream_execution_plan_valid(plan));
  assert(!plan.errors.empty());
}

void test_deepstream_execution_plan_resolves_repo_root_relative_model_paths() {
  const auto temp_root =
      std::filesystem::temp_directory_path() / ("robot_life_cpp_ds_root_" + robot_life_cpp::common::new_id());
  std::filesystem::create_directories(temp_root / "configs");
  std::filesystem::create_directories(temp_root / "models/deepstream/face");
  {
    std::ofstream out(temp_root / "models/deepstream/face/pgie_face.txt");
    assert(out.good());
    out << "face\n";
  }
  {
    std::ofstream out(temp_root / "configs/deepstream_4vision.yaml");
    assert(out.good());
    out << "branch.face.model_config_path: models/deepstream/face/pgie_face.txt\n";
  }

  ScopedCurrentPath cwd{temp_root};
  robot_life_cpp::perception::DeepStreamGraphConfig config{};
  std::string error{};
  assert(robot_life_cpp::perception::load_deepstream_graph_config(
      temp_root / "configs/deepstream_4vision.yaml", &config, &error));
  const auto plan = robot_life_cpp::perception::build_deepstream_execution_plan(
      config, temp_root / "configs/deepstream_4vision.yaml");
  assert(plan.branches[0].model_config_exists);
  assert(plan.branches[0].model_config_path == std::filesystem::path{"models/deepstream/face/pgie_face.txt"});

  std::filesystem::remove_all(temp_root);
}

void test_event_injector_deduplicates_and_injects_into_live_loop() {
  robot_life_cpp::runtime::DetectionEventInjector injector{};
  robot_life_cpp::runtime::LiveLoop loop{};

  std::vector<robot_life_cpp::common::DetectionResult> detections{};
  detections.push_back(build_detection(
      "deepstream_face",
      std::string(robot_life_cpp::common::visual_contract::EVENT_FACE_DETECTED),
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "10"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_TRACK_ID), "person_track_1"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,100,120"},
      }));
  detections.push_back(detections.front());

  const auto emitted = injector.build_events(detections, 50.0);
  assert(emitted.size() == 1);
  const auto injected = injector.inject_into(&loop, detections, 50.3);
  assert(injected == 1);
  loop.tick();
  const auto snap = loop.snapshot();
  assert(snap.stable_events_last_tick >= 1 || snap.scene_candidates_last_tick >= 0);
}

void test_event_injector_skips_invalid_visual_and_caps_batch() {
  robot_life_cpp::runtime::DetectionEventInjector injector{
      {.dedupe_window_s = 0.0, .cooldown_window_s = 0.0, .max_events_per_batch = 2}};

  std::vector<robot_life_cpp::common::DetectionResult> detections{};
  detections.push_back(build_detection(
      "deepstream_face",
      std::string(robot_life_cpp::common::visual_contract::EVENT_FACE_DETECTED),
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "1"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_TRACK_ID), "person_track_1"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,100,120"},
      }));
  detections.push_back(build_detection(
      "deepstream_face",
      std::string(robot_life_cpp::common::visual_contract::EVENT_FACE_DETECTED),
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "2"},
      }));
  detections.push_back(build_detection(
      "deepstream_pose",
      std::string(robot_life_cpp::common::visual_contract::EVENT_POSE_DETECTED),
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "3"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_TRACK_ID), "person_track_1"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,100,120"},
      }));
  detections.push_back(build_detection(
      "deepstream_scene",
      std::string(robot_life_cpp::common::visual_contract::EVENT_SCENE_CONTEXT_DETECTED),
      {
          {std::string(robot_life_cpp::common::visual_contract::KEY_CAMERA_ID), "front_cam"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_FRAME_ID), "4"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_TRACK_ID), "person_track_1"},
          {std::string(robot_life_cpp::common::visual_contract::KEY_BBOX), "10,20,100,120"},
      }));

  const auto emitted = injector.build_events(detections, 70.0);
  assert(emitted.size() == 2);
  for (const auto& event : emitted) {
    assert(event.payload.contains("bbox"));
    assert(event.payload.contains("track_id"));
  }
}

void test_runtime_health_monitor_tracks_phase_and_components() {
  robot_life_cpp::runtime::RuntimeHealthMonitor monitor{};
  monitor.set_phase(robot_life_cpp::runtime::RuntimePhase::Starting, "boot");
  monitor.update_component({"backend", false, "starting", "spawn"});
  monitor.update_component({"core", true, "ready", "loop"});
  monitor.set_phase(robot_life_cpp::runtime::RuntimePhase::Ready, "all systems go");

  assert(monitor.phase() == robot_life_cpp::runtime::RuntimePhase::Ready);
  assert(monitor.phase_name() == "ready");
  const auto backend = monitor.component("backend");
  assert(backend.has_value());
  assert(backend->state == "starting");
  const auto snapshot = monitor.snapshot();
  assert(snapshot.components.size() == 2);
  assert(snapshot.detail == "all systems go");
}
}  // namespace

int main() {
  test_live_loop_smoke();
  test_hysteresis_hold_and_release();
  test_module_catalog_uniqueness();
  test_decision_queue_priority_and_replace();
  test_cooldown_manager_global_and_scene_rules();
  test_cooldown_manager_uses_configured_proactive_scenes();
  test_arbitration_runtime_queue_and_dequeue();
  test_temporal_event_layer_derives_gaze_and_wave();
  test_entity_tracker_reuses_identity_tracks();
  test_resource_manager_preemption_and_release();
  test_behavior_safety_guard_blocks_conflict_without_interrupt();
  test_behavior_executor_degrade_and_resume_queue();
  test_runtime_execution_manager_history();
  test_runtime_telemetry_aggregates_stage_metrics();
  test_runtime_life_state_snapshot_flags();
  test_runtime_life_state_uses_configured_taxonomy_groups();
  test_runtime_execution_support_finalize_and_resume_enqueue();
  test_profile_registry_parses_default_profile_and_names();
  test_visual_contract_validates_detection_payloads();
  test_pipeline_factory_selects_backend_by_profile();
  test_runtime_tuning_profile_loads_single_source_values();
  test_runtime_tuning_store_reloads_after_file_change();
  test_runtime_tuning_applies_to_graph_config();
  test_scene_aggregator_uses_configured_taxonomy_mapping();
  test_load_shedder_reduces_preview_and_batch_under_pressure();
  test_load_shedder_preserves_configured_batch_cap_when_normal();
  test_debug_dashboard_renderers_include_runtime_and_load_information();
  test_deepstream_protocol_roundtrip();
  test_deepstream_process_backend_streams_mock_detections();
  test_deepstream_launch_spec_prefers_mock_on_non_linux_real_request();
  test_deepstream_launch_spec_honors_explicit_mock_mode();
  test_deepstream_runner_factory_selects_real_and_mock();
  test_deepstream_adapter_normalizes_and_deduplicates();
  test_deepstream_export_contract_validates_required_keys();
  test_deepstream_exporter_exports_protocol_lines_consumed_by_adapter();
  test_deepstream_exporter_skips_empty_frame_and_missing_required_fields();
  test_deepstream_exporter_rejects_malformed_bbox_and_deduplicates_frame_objects();
  test_deepstream_exporter_allows_partial_optional_payloads();
  test_deepstream_graph_emits_four_branches_and_tracks_stats();
  test_deepstream_graph_branch_toggle_and_sampling();
  test_deepstream_graph_configures_shared_stages_and_output_cap();
  test_deepstream_graph_loads_external_binding_config();
  test_deepstream_execution_plan_resolves_branch_assets_and_renders_app_config();
  test_deepstream_execution_plan_reports_missing_model_configs();
  test_deepstream_execution_plan_resolves_repo_root_relative_model_paths();
  test_deepstream_execution_plan_validates_branch_specific_model_properties();
  test_deepstream_branch_event_mapping_face_identity_and_attention();
  test_deepstream_branch_event_mapping_pose_gesture_and_wave();
  test_deepstream_branch_event_mapping_motion_direction();
  test_deepstream_branch_event_mapping_scene_object_class();
  test_event_injector_deduplicates_and_injects_into_live_loop();
  test_event_injector_skips_invalid_visual_and_caps_batch();
  test_deepstream_event_flow_face_end_to_end();
  test_deepstream_event_flow_pose_gesture_end_to_end();
  test_deepstream_event_flow_motion_end_to_end();
  test_deepstream_event_flow_scene_object_end_to_end();
  test_runtime_health_monitor_tracks_phase_and_components();
  return 0;
}
