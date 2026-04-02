#pragma once

#include <string>
#include <vector>

namespace robot_life_cpp::runtime {

struct CudaDeviceInfo {
  int index{0};
  std::string name;
  std::size_t total_memory_bytes{0};
  int multiprocessor_count{0};
  int major{0};
  int minor{0};
};

struct CudaRuntimeInfo {
  bool available{false};
  int device_count{0};
  std::vector<CudaDeviceInfo> devices{};
  std::string message;
};

CudaRuntimeInfo probe_cuda_runtime();

}  // namespace robot_life_cpp::runtime
