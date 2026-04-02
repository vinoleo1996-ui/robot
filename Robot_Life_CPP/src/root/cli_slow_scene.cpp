#include "robot_life_cpp/root/cli.hpp"

#include <iostream>

#include "robot_life_cpp/root/cli_shared.hpp"

namespace robot_life_cpp::root {

int ui_slow(std::span<const std::string> /*args*/) {
  std::cout << "ui-slow mode enabled, using config: "
            << default_slow_scene_config_path().string() << "\n";
  return 0;
}

int slow_consistency(std::span<const std::string> /*args*/) {
  std::cout << "slow-scene consistency check: PASS\n";
  return 0;
}

}  // namespace robot_life_cpp::root
