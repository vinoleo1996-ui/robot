#include "robot_life_cpp/common/schemas.hpp"

#include <atomic>
#include <sstream>
#include <thread>

namespace robot_life_cpp::common {

namespace {
std::atomic<std::uint64_t> g_id_counter{1};
}

std::string to_string(EventPriority priority) {
  switch (priority) {
    case EventPriority::P0:
      return "P0";
    case EventPriority::P1:
      return "P1";
    case EventPriority::P2:
      return "P2";
    case EventPriority::P3:
      return "P3";
  }
  return "P2";
}

std::string to_string(DecisionMode mode) {
  switch (mode) {
    case DecisionMode::Execute:
      return "EXECUTE";
    case DecisionMode::SoftInterrupt:
      return "SOFT_INTERRUPT";
    case DecisionMode::HardInterrupt:
      return "HARD_INTERRUPT";
    case DecisionMode::DegradeAndExecute:
      return "DEGRADE_AND_EXECUTE";
    case DecisionMode::Queue:
      return "QUEUE";
    case DecisionMode::Drop:
      return "DROP";
  }
  return "DROP";
}

int priority_rank(EventPriority priority) { return static_cast<int>(priority); }

std::string new_id() {
  const auto counter = g_id_counter.fetch_add(1, std::memory_order_relaxed);
  std::ostringstream oss;
  oss << "rlcpp-" << counter;
  return oss.str();
}

double now_mono() {
  using clock = std::chrono::steady_clock;
  const auto now = clock::now().time_since_epoch();
  return std::chrono::duration<double>(now).count();
}

double now_wall() {
  using clock = std::chrono::system_clock;
  const auto now = clock::now().time_since_epoch();
  return std::chrono::duration<double>(now).count();
}

}  // namespace robot_life_cpp::common
