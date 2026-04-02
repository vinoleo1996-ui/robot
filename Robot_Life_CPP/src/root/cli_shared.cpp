#include "robot_life_cpp/root/cli_shared.hpp"

#include <filesystem>

namespace robot_life_cpp::root {

std::filesystem::path default_config_path() {
  return std::filesystem::path("configs/app.yaml");
}

std::filesystem::path default_detector_config_path() {
  return std::filesystem::path("configs/detectors.yaml");
}

std::filesystem::path default_slow_scene_config_path() {
  return std::filesystem::path("configs/slow_scene.yaml");
}

std::filesystem::path default_stabilizer_config_path() {
  return std::filesystem::path("configs/stabilizer.yaml");
}

std::filesystem::path default_runtime_tuning_path() {
  return std::filesystem::path("configs/runtime_tuning.yaml");
}

}  // namespace robot_life_cpp::root
