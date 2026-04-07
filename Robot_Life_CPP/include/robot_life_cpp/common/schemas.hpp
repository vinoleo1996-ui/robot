#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace robot_life_cpp::common {

using Payload = std::unordered_map<std::string, std::string>;

enum class EventPriority : std::uint8_t {
  P0 = 0,
  P1 = 1,
  P2 = 2,
  P3 = 3,
};

enum class DecisionMode : std::uint8_t {
  Execute = 0,
  SoftInterrupt = 1,
  HardInterrupt = 2,
  DegradeAndExecute = 3,
  Queue = 4,
  Drop = 5,
};

std::string to_string(EventPriority priority);
std::string to_string(DecisionMode mode);
int priority_rank(EventPriority priority);

std::string new_id();
double now_mono();
double now_wall();

struct DetectionResult {
  std::string trace_id;
  std::string source;
  std::string detector;
  std::string event_type;
  double timestamp{0.0};
  double confidence{0.0};
  Payload payload{};
};

struct RawEvent {
  std::string event_id;
  std::string trace_id;
  std::string event_type;
  EventPriority priority{EventPriority::P2};
  double timestamp_monotonic{0.0};
  double confidence{0.0};
  std::string source;
  int ttl_ms{3000};
  std::string cooldown_key;
  Payload payload{};
};

struct StableEvent {
  std::string stable_event_id;
  std::string base_event_id;
  std::string trace_id;
  std::string event_type;
  EventPriority priority{EventPriority::P2};
  double valid_until_monotonic{0.0};
  std::vector<std::string> stabilized_by{};
  Payload payload{};
};

struct SceneCandidate {
  std::string scene_id;
  std::string trace_id;
  std::string scene_type;
  std::vector<std::string> based_on_events{};
  double score_hint{0.0};
  double valid_until_monotonic{0.0};
  std::optional<std::string> target_id{};
  Payload payload{};
};

struct ArbitrationResult {
  std::string decision_id;
  std::string trace_id;
  std::optional<std::string> scene_type{};
  std::optional<std::string> target_id{};
  std::string target_behavior;
  EventPriority priority{EventPriority::P2};
  DecisionMode mode{DecisionMode::Execute};
  std::vector<std::string> required_resources{};
  std::vector<std::string> optional_resources{};
  std::optional<std::string> degraded_behavior{};
  bool resume_previous{true};
  std::string reason;
};

struct ExecutionResult {
  std::string execution_id;
  std::string trace_id;
  std::string behavior_id;
  std::string status;
  bool interrupted{false};
  bool degraded{false};
  double started_at{0.0};
  double ended_at{0.0};
};

}  // namespace robot_life_cpp::common
