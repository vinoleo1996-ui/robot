#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace robot_life_cpp::runtime {

enum class RuntimePhase : std::uint8_t {
  Starting = 0,
  Warming = 1,
  Ready = 2,
  Degraded = 3,
  Failed = 4,
  Stopping = 5,
  Stopped = 6,
};

struct ComponentHealth {
  std::string name;
  bool healthy{false};
  std::string state;
  std::string detail;
};

struct RuntimeHealthSnapshot {
  RuntimePhase phase{RuntimePhase::Starting};
  std::vector<ComponentHealth> components{};
  std::string detail;
};

class RuntimeHealthMonitor {
 public:
  void set_phase(RuntimePhase phase, std::string detail = {});
  RuntimePhase phase() const;
  std::string phase_name() const;
  void update_component(ComponentHealth component);
  std::optional<ComponentHealth> component(const std::string& name) const;
  RuntimeHealthSnapshot snapshot() const;

 private:
  static std::string to_string(RuntimePhase phase);

  RuntimeHealthSnapshot snapshot_{};
};

}  // namespace robot_life_cpp::runtime
