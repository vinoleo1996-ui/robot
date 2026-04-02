#include "robot_life_cpp/runtime/execution_support.hpp"

#include "robot_life_cpp/event_engine/arbitration_runtime.hpp"
#include "robot_life_cpp/runtime/telemetry.hpp"

namespace robot_life_cpp::runtime {

void finalize_execution(
    std::vector<common::ExecutionResult>* execution_results,
    const common::ExecutionResult& execution,
    TelemetrySink* telemetry,
    const std::string& stage_name,
    double started_at,
    std::optional<double> ended_at,
    bool async_mode,
    bool tick_mode) {
  if (execution_results != nullptr) {
    execution_results->push_back(execution);
  }

  emit_stage_trace(
      telemetry,
      execution.trace_id,
      stage_name,
      "ok",
      {
          {"behavior_id", execution.behavior_id},
          {"status", execution.status},
          {"degraded", execution.degraded ? "true" : "false"},
          {"interrupted", execution.interrupted ? "true" : "false"},
          {"async", async_mode ? "true" : "false"},
          {"tick_mode", tick_mode ? "true" : "false"},
      },
      started_at,
      ended_at.value_or(common::now_mono()));
}

bool enqueue_resumed_decision(
    event_engine::ArbitrationRuntime* arbitration_runtime,
    TelemetrySink* telemetry,
    const common::ArbitrationResult& resumed,
    double now_mono_s) {
  if (arbitration_runtime == nullptr) {
    return false;
  }

  auto queued = arbitration_runtime->submit(
      common::SceneCandidate{
          .scene_id = common::new_id(),
          .trace_id = resumed.trace_id,
          .scene_type = "resume_scene",
          .based_on_events = {},
          .score_hint = 1.0,
          .valid_until_monotonic = now_mono_s + 1.0,
          .target_id = std::nullopt,
          .payload = {{"resume_target_behavior", resumed.target_behavior}},
      },
      common::EventPriority::P0,
      std::nullopt,
      now_mono_s);

  const bool enqueued = !queued.has_value();
  emit_stage_trace(
      telemetry,
      resumed.trace_id,
      "resume_enqueue",
      enqueued ? "queued" : "executed",
      {
          {"target_behavior", resumed.target_behavior},
          {"priority", common::to_string(resumed.priority)},
          {"reason", resumed.reason},
      },
      now_mono_s,
      now_mono_s);
  return enqueued;
}

}  // namespace robot_life_cpp::runtime
