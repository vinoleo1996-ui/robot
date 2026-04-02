#pragma once

#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/perception/base.hpp"
#include "robot_life_cpp/runtime/health_monitor.hpp"
#include "robot_life_cpp/runtime/load_shedder.hpp"
#include "robot_life_cpp/runtime/runtime_tuning.hpp"
#include "robot_life_cpp/runtime/telemetry.hpp"

namespace robot_life_cpp::runtime {

struct DebugDashboardData {
  RuntimeSnapshot runtime{};
  RuntimeHealthSnapshot health{};
  perception::BackendStats backend{};
  std::unordered_map<std::string, StageAggregate> telemetry{};
  RuntimeTuningProfile tuning{};
  LoadShedderDecision load_shed{};
  std::vector<common::DetectionResult> preview_detections{};
  std::string platform;
  std::string gpu_summary;
  double process_memory_mb{0.0};
};

std::string render_debug_dashboard_json(const DebugDashboardData& data);
std::string render_debug_dashboard_html(const DebugDashboardData& data);
bool write_debug_dashboard_files(
    const DebugDashboardData& data,
    const std::filesystem::path& html_path,
    const std::filesystem::path& json_path);

}  // namespace robot_life_cpp::runtime
