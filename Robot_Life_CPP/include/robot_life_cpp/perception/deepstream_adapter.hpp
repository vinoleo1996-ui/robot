#pragma once

#include <optional>
#include <string>

#include "robot_life_cpp/bridge/deepstream_protocol.hpp"
#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::perception {

class DeepStreamAdapter {
 public:
  std::optional<common::DetectionResult> adapt_detection(
      const bridge::DeepStreamEnvelope& envelope);

 private:
  std::string last_signature_{};
};

}  // namespace robot_life_cpp::perception
