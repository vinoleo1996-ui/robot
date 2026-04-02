#pragma once

#include <optional>
#include <string>
#include <unordered_map>

namespace robot_life_cpp::runtime {

std::string intent_for_state(const std::optional<std::string>& state_name);
std::string intent_from_snapshot(
    const std::unordered_map<std::string, std::string>& snapshot);

}  // namespace robot_life_cpp::runtime
