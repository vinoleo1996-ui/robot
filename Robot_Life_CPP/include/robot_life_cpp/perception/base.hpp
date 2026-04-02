#pragma once

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::perception {

struct BackendHealth {
  bool healthy{false};
  std::string state;
  std::string detail;
};

struct BackendStats {
  std::string backend_id;
  bool running{false};
  std::size_t delivered_batches{0};
  std::size_t delivered_detections{0};
};

class Backend {
 public:
  virtual ~Backend() = default;

  virtual std::string backend_id() const = 0;
  virtual bool start() = 0;
  virtual void stop() = 0;
  virtual std::vector<common::DetectionResult> poll(std::size_t max_items) = 0;
  virtual BackendHealth health() const = 0;
  virtual BackendStats stats() const = 0;
};

std::unique_ptr<Backend> make_null_backend(std::string backend_id, std::string detail);

}  // namespace robot_life_cpp::perception
