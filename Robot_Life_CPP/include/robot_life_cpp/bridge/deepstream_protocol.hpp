#pragma once

#include <optional>
#include <string>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::bridge {

struct DeepStreamHealthMessage {
  std::string state;
  std::string detail;
};

struct DeepStreamEnvelope {
  enum class Kind {
    Health,
    Detection,
  };

  Kind kind{Kind::Health};
  std::optional<DeepStreamHealthMessage> health{};
  std::optional<common::DetectionResult> detection{};
};

std::string encode_health_line(const DeepStreamHealthMessage& health);
std::string encode_detection_line(const common::DetectionResult& detection);
std::optional<DeepStreamEnvelope> parse_deepstream_line(const std::string& line);

}  // namespace robot_life_cpp::bridge
