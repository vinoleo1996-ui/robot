#include "robot_life_cpp/runtime/telemetry.hpp"

#include <algorithm>
#include <numeric>

namespace robot_life_cpp::runtime {

std::optional<double> StageTrace::duration_ms() const {
  if (!ended_at.has_value()) {
    return std::nullopt;
  }
  return std::max(0.0, (*ended_at - started_at) * 1000.0);
}

AggregatingTelemetrySink::AggregatingTelemetrySink(std::size_t max_traces, std::size_t max_stage_samples)
    : max_traces_(std::max<std::size_t>(1, max_traces)),
      max_stage_samples_(std::max<std::size_t>(1, max_stage_samples)) {}

void AggregatingTelemetrySink::emit(const StageTrace& trace) {
  traces_.push_back(trace);
  while (traces_.size() > max_traces_) {
    traces_.pop_front();
  }

  stage_counts_[trace.stage] += 1;
  status_counts_[trace.stage][trace.status] += 1;
  if (auto duration = trace.duration_ms(); duration.has_value()) {
    auto& samples = durations_[trace.stage];
    samples.push_back(*duration);
    while (samples.size() > max_stage_samples_) {
      samples.pop_front();
    }
  }
  last_payload_[trace.stage] = trace.payload;
  last_trace_id_[trace.stage] = trace.trace_id;
}

void AggregatingTelemetrySink::reset() {
  traces_.clear();
  stage_counts_.clear();
  status_counts_.clear();
  durations_.clear();
  last_payload_.clear();
  last_trace_id_.clear();
}

std::unordered_map<std::string, StageAggregate> AggregatingTelemetrySink::snapshot() const {
  std::unordered_map<std::string, StageAggregate> out{};
  for (const auto& [stage, count] : stage_counts_) {
    StageAggregate aggregate{};
    aggregate.stage = stage;
    aggregate.count = count;
    auto status_it = status_counts_.find(stage);
    if (status_it != status_counts_.end()) {
      aggregate.statuses = status_it->second;
    }
    auto duration_it = durations_.find(stage);
    if (duration_it != durations_.end() && !duration_it->second.empty()) {
      const auto& samples = duration_it->second;
      const auto sum = std::accumulate(samples.begin(), samples.end(), 0.0);
      aggregate.avg_duration_ms = sum / static_cast<double>(samples.size());
      aggregate.max_duration_ms = *std::max_element(samples.begin(), samples.end());
      aggregate.min_duration_ms = *std::min_element(samples.begin(), samples.end());
    }
    auto payload_it = last_payload_.find(stage);
    if (payload_it != last_payload_.end()) {
      aggregate.last_payload = payload_it->second;
    }
    auto trace_it = last_trace_id_.find(stage);
    if (trace_it != last_trace_id_.end()) {
      aggregate.last_trace_id = trace_it->second;
    }
    out[stage] = std::move(aggregate);
  }
  return out;
}

StageTrace build_stage_trace(
    const std::string& trace_id,
    const std::string& stage,
    std::string status,
    common::Payload payload,
    std::optional<double> started_at,
    std::optional<double> ended_at) {
  StageTrace trace{};
  trace.trace_id = trace_id;
  trace.stage = stage;
  trace.status = std::move(status);
  trace.started_at = started_at.value_or(common::now_mono());
  trace.ended_at = ended_at;
  trace.payload = std::move(payload);
  return trace;
}

StageTrace emit_stage_trace(
    TelemetrySink* sink,
    const std::string& trace_id,
    const std::string& stage,
    std::string status,
    common::Payload payload,
    std::optional<double> started_at,
    std::optional<double> ended_at) {
  auto trace = build_stage_trace(
      trace_id,
      stage,
      std::move(status),
      std::move(payload),
      started_at,
      ended_at.value_or(common::now_mono()));
  if (sink != nullptr) {
    sink->emit(trace);
  }
  return trace;
}

}  // namespace robot_life_cpp::runtime
