#include "robot_life_cpp/runtime/health_monitor.hpp"

#include <algorithm>
#include <utility>
#include <utility>

namespace robot_life_cpp::runtime {

void RuntimeHealthMonitor::set_phase(RuntimePhase phase, std::string detail) {
  snapshot_.phase = phase;
  snapshot_.detail = std::move(detail);
}

RuntimePhase RuntimeHealthMonitor::phase() const { return snapshot_.phase; }

std::string RuntimeHealthMonitor::phase_name() const { return to_string(snapshot_.phase); }

void RuntimeHealthMonitor::update_component(ComponentHealth component) {
  const auto it = std::find_if(snapshot_.components.begin(), snapshot_.components.end(), [&](const auto& item) {
    return item.name == component.name;
  });
  if (it == snapshot_.components.end()) {
    snapshot_.components.push_back(std::move(component));
    return;
  }
  *it = std::move(component);
}

std::optional<ComponentHealth> RuntimeHealthMonitor::component(const std::string& name) const {
  const auto it = std::find_if(snapshot_.components.begin(), snapshot_.components.end(), [&](const auto& item) {
    return item.name == name;
  });
  if (it == snapshot_.components.end()) {
    return std::nullopt;
  }
  return *it;
}

RuntimeHealthSnapshot RuntimeHealthMonitor::snapshot() const { return snapshot_; }

std::string RuntimeHealthMonitor::to_string(RuntimePhase phase) {
  switch (phase) {
    case RuntimePhase::Starting:
      return "starting";
    case RuntimePhase::Warming:
      return "warming";
    case RuntimePhase::Ready:
      return "ready";
    case RuntimePhase::Degraded:
      return "degraded";
    case RuntimePhase::Failed:
      return "failed";
    case RuntimePhase::Stopping:
      return "stopping";
    case RuntimePhase::Stopped:
      return "stopped";
  }
  return "unknown";
}

}  // namespace robot_life_cpp::runtime
