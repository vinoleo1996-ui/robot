#include "robot_life_cpp/perception/base.hpp"

#include <utility>

namespace robot_life_cpp::perception {

namespace {
class NullBackend final : public Backend {
 public:
  NullBackend(std::string backend_id, std::string detail)
      : backend_id_(std::move(backend_id)), detail_(std::move(detail)) {}

  std::string backend_id() const override { return backend_id_; }

  bool start() override {
    running_ = true;
    return true;
  }

  void stop() override { running_ = false; }

  std::vector<common::DetectionResult> poll(std::size_t /*max_items*/) override {
    if (running_) {
      ++delivered_batches_;
    }
    return {};
  }

  BackendHealth health() const override {
    return {.healthy = true, .state = running_ ? "ready" : "idle", .detail = detail_};
  }

  BackendStats stats() const override {
    return {.backend_id = backend_id_,
            .running = running_,
            .delivered_batches = delivered_batches_,
            .delivered_detections = 0};
  }

 private:
  std::string backend_id_;
  std::string detail_;
  bool running_{false};
  std::size_t delivered_batches_{0};
};
}  // namespace

std::unique_ptr<Backend> make_null_backend(std::string backend_id, std::string detail) {
  return std::make_unique<NullBackend>(std::move(backend_id), std::move(detail));
}

}  // namespace robot_life_cpp::perception
