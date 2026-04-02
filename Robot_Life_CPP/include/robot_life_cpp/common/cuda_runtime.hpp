#pragma once

#include <filesystem>
#include <utility>
#include <vector>

namespace robot_life_cpp::common {

std::vector<std::filesystem::path> discover_cuda_lib_dirs();
std::vector<std::filesystem::path> prepend_cuda_library_path();
std::pair<int, int> preload_cuda_shared_libs();
std::pair<int, int> ensure_cuda_runtime_loaded();

}  // namespace robot_life_cpp::common
