#pragma once

#include <memory>
#include <string>

#include "robot_life_cpp/perception/deepstream_graph.hpp"

namespace robot_life_cpp::perception {

struct DeepStreamRunnerRequest {
  int frames{16};
  int interval_ms{10};
  int metadata_ready_timeout_ms{800};
  int shutdown_timeout_ms{500};
  std::string source{"deepstream_mock_camera"};
  std::string mode{"mock"};
  std::string deepstream_app;
  std::string write_app_config;
  std::string metadata_path;
};

class DeepStreamRunner {
 public:
  virtual ~DeepStreamRunner() = default;

  virtual std::string runner_id() const = 0;
  virtual int run(
      const DeepStreamRunnerRequest& request,
      DeepStreamFourVisionGraph* graph,
      const DeepStreamExecutionPlan& plan) const = 0;
};

std::unique_ptr<DeepStreamRunner> make_deepstream_runner(const std::string& mode);

}  // namespace robot_life_cpp::perception
