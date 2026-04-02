#pragma once

#include <deque>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

struct StageTrace {
  std::string trace_id;
  std::string stage;
  std::string status{"ok"};
  double started_at{0.0};
  std::optional<double> ended_at{};
  common::Payload payload{};

  std::optional<double> duration_ms() const;
};

struct StageAggregate {
  std::string stage;
  int count{0};
  std::unordered_map<std::string, int> statuses{};
  std::optional<double> avg_duration_ms{};
  std::optional<double> max_duration_ms{};
  std::optional<double> min_duration_ms{};
  common::Payload last_payload{};
  std::optional<std::string> last_trace_id{};
};

class TelemetrySink {
 public:
  virtual ~TelemetrySink() = default;
  virtual void emit(const StageTrace& trace) = 0;
};

class AggregatingTelemetrySink : public TelemetrySink {
 public:
  explicit AggregatingTelemetrySink(std::size_t max_traces = 2048, std::size_t max_stage_samples = 512);

  void emit(const StageTrace& trace) override;
  void reset();
  std::unordered_map<std::string, StageAggregate> snapshot() const;

 private:
  std::size_t max_traces_{2048};
  std::size_t max_stage_samples_{512};
  std::deque<StageTrace> traces_{};
  std::unordered_map<std::string, int> stage_counts_{};
  std::unordered_map<std::string, std::unordered_map<std::string, int>> status_counts_{};
  std::unordered_map<std::string, std::deque<double>> durations_{};
  std::unordered_map<std::string, common::Payload> last_payload_{};
  std::unordered_map<std::string, std::string> last_trace_id_{};
};

StageTrace build_stage_trace(
    const std::string& trace_id,
    const std::string& stage,
    std::string status = "ok",
    common::Payload payload = {},
    std::optional<double> started_at = std::nullopt,
    std::optional<double> ended_at = std::nullopt);

StageTrace emit_stage_trace(
    TelemetrySink* sink,
    const std::string& trace_id,
    const std::string& stage,
    std::string status = "ok",
    common::Payload payload = {},
    std::optional<double> started_at = std::nullopt,
    std::optional<double> ended_at = std::nullopt);

}  // namespace robot_life_cpp::runtime

