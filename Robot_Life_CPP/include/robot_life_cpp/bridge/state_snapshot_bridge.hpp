#pragma once

#include <mutex>
#include <string>

#include "robot_life_cpp/runtime/live_loop.hpp"

namespace robot_life_cpp::bridge {

class StateSnapshotBridge {
 public:
  void publish(runtime::RuntimeSnapshot snapshot);
  runtime::RuntimeSnapshot latest() const;
  std::string latest_json() const;

 private:
  mutable std::mutex mu_;
  runtime::RuntimeSnapshot latest_{};
};

}  // namespace robot_life_cpp::bridge
