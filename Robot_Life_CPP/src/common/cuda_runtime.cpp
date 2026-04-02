#include "robot_life_cpp/common/cuda_runtime.hpp"

#include <algorithm>
#include <cstdlib>
#include <set>
#include <string>
#include <vector>

namespace robot_life_cpp::common {

std::vector<std::filesystem::path> discover_cuda_lib_dirs() {
  std::vector<std::filesystem::path> result{};
  std::set<std::filesystem::path> uniq{};
  const std::vector<std::filesystem::path> candidates{
      "/usr/local/cuda/lib64",
      "/usr/local/cuda/lib",
      "/usr/lib/x86_64-linux-gnu",
  };
  for (const auto& path : candidates) {
    if (std::filesystem::exists(path) && std::filesystem::is_directory(path) &&
        uniq.insert(path).second) {
      result.push_back(path);
    }
  }
  return result;
}

std::vector<std::filesystem::path> prepend_cuda_library_path() {
  const auto dirs = discover_cuda_lib_dirs();
  if (dirs.empty()) {
    return {};
  }

  const char* old_env = std::getenv("LD_LIBRARY_PATH");
  std::string current = old_env == nullptr ? "" : old_env;
  std::string merged{};
  for (const auto& dir : dirs) {
    if (!merged.empty()) {
      merged += ":";
    }
    merged += dir.string();
  }
  if (!current.empty()) {
    merged += ":" + current;
  }
  setenv("LD_LIBRARY_PATH", merged.c_str(), 1);
  return dirs;
}

std::pair<int, int> preload_cuda_shared_libs() {
  // C++ runtime currently relies on link-time CUDA loading.
  // We keep the API parity and return a successful no-op result.
  const auto dirs = discover_cuda_lib_dirs();
  return {static_cast<int>(dirs.size()), 0};
}

std::pair<int, int> ensure_cuda_runtime_loaded() {
  prepend_cuda_library_path();
  return preload_cuda_shared_libs();
}

}  // namespace robot_life_cpp::common
