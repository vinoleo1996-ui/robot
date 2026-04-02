#pragma once

#include <cstddef>
#include <string>

#include "robot_life_cpp/perception/base.hpp"
#include "robot_life_cpp/runtime/live_loop.hpp"

namespace robot_life_cpp::runtime {

enum class LoadPressure : std::uint8_t {
  Normal = 0,
  Warning = 1,
  Shed = 2,
};

struct LoadShedderConfig {
  std::size_t warning_pending_events{64};
  std::size_t shed_pending_events{192};
  std::size_t warning_scene_candidates{4};
  std::size_t shed_scene_candidates{8};
  std::size_t warning_max_events_per_batch{32};
  std::size_t shed_max_events_per_batch{16};
  int normal_preview_every_ticks{1};
  int warning_preview_every_ticks{2};
  int shed_preview_every_ticks{4};
  int normal_telemetry_every_ticks{1};
  int warning_telemetry_every_ticks{2};
  int shed_telemetry_every_ticks{4};
};

struct LoadShedderInput {
  RuntimeSnapshot runtime{};
  perception::BackendStats backend{};
  bool ui_enabled{false};
  std::size_t configured_max_events_per_batch{64};
};

struct LoadShedderDecision {
  LoadPressure pressure{LoadPressure::Normal};
  std::size_t max_events_per_batch{64};
  int preview_every_ticks{1};
  int telemetry_every_ticks{1};
  bool preview_enabled{true};
  std::string reason{"normal"};
};

class RuntimeLoadShedder {
 public:
  explicit RuntimeLoadShedder(LoadShedderConfig config = {});

  LoadShedderDecision decide(const LoadShedderInput& input) const;

 private:
  LoadShedderConfig config_{};
};

std::string to_string(LoadPressure pressure);

}  // namespace robot_life_cpp::runtime
