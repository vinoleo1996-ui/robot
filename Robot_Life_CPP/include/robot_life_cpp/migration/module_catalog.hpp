#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace robot_life_cpp::migration {

struct ModuleMapping {
  std::string python_module_path;
  std::string cpp_target_unit;
  std::string layer;
  bool implemented{false};
};

const std::vector<ModuleMapping>& module_catalog();
std::size_t implemented_module_count();
std::size_t total_module_count();

}  // namespace robot_life_cpp::migration
