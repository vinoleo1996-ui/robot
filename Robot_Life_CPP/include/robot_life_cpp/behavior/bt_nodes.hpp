#pragma once

#include <string>

namespace robot_life_cpp::behavior {

struct NodeResult {
  std::string node_name;
  std::string status;
  std::string details;
};

NodeResult run_node(
    const std::string& node_name,
    const std::string& behavior_id,
    bool degraded = false);

}  // namespace robot_life_cpp::behavior
