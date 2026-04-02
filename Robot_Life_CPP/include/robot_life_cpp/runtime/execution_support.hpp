#pragma once

#include <optional>
#include <string>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {
class ArbitrationRuntime;
}

namespace robot_life_cpp::runtime {

class TelemetrySink;

void finalize_execution(
    std::vector<common::ExecutionResult>* execution_results,
    const common::ExecutionResult& execution,
    TelemetrySink* telemetry,
    const std::string& stage_name,
    double started_at,
    std::optional<double> ended_at = std::nullopt,
    bool async_mode = false,
    bool tick_mode = false);

bool enqueue_resumed_decision(
    event_engine::ArbitrationRuntime* arbitration_runtime,
    TelemetrySink* telemetry,
    const common::ArbitrationResult& resumed,
    double now_mono_s = common::now_mono());

}  // namespace robot_life_cpp::runtime

