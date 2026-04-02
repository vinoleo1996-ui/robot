#pragma once

#include <filesystem>
#include <cstdio>
#include <deque>
#include <string>

#include "robot_life_cpp/perception/base.hpp"

namespace robot_life_cpp::perception {

struct DeepStreamLaunchSpec {
  std::string requested_mode{"auto"};
  std::string resolved_mode{"mock"};
  std::string command;
  std::string detail;
  std::filesystem::path graph_config_path;
  std::filesystem::path deepstream_app_path;
  std::filesystem::path metadata_path;
  std::filesystem::path generated_app_config_path;
  bool real_runtime_available{false};
};

DeepStreamLaunchSpec resolve_deepstream_launch_spec();

class DeepStreamProcessBackend final : public Backend {
 public:
  DeepStreamProcessBackend();
  ~DeepStreamProcessBackend() override;

  std::string backend_id() const override;
  bool start() override;
  void stop() override;
  std::vector<common::DetectionResult> poll(std::size_t max_items) override;
  BackendHealth health() const override;
  BackendStats stats() const override;
  const DeepStreamLaunchSpec& launch_spec() const;

 private:
  bool spawn_process();
  void refresh_pipe();

  FILE* pipe_{nullptr};
  std::deque<common::DetectionResult> queue_{};
  bool manual_stop_{true};
  BackendHealth health_{.healthy = false, .state = "idle", .detail = "not started"};
  BackendStats stats_{.backend_id = "deepstream", .running = false, .delivered_batches = 0, .delivered_detections = 0};
  DeepStreamLaunchSpec launch_spec_{};
};

}  // namespace robot_life_cpp::perception
