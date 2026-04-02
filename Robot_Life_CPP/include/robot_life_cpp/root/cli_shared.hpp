#pragma once

#include <filesystem>

namespace robot_life_cpp::root {

std::filesystem::path default_config_path();
std::filesystem::path default_detector_config_path();
std::filesystem::path default_slow_scene_config_path();
std::filesystem::path default_stabilizer_config_path();
std::filesystem::path default_runtime_tuning_path();

}  // namespace robot_life_cpp::root
