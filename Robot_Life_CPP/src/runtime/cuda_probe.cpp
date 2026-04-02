#include "robot_life_cpp/runtime/cuda_probe.hpp"

#if ROBOT_LIFE_CPP_HAS_CUDA
#include <cuda_runtime_api.h>
#endif

namespace robot_life_cpp::runtime {

CudaRuntimeInfo probe_cuda_runtime() {
  CudaRuntimeInfo info{};

#if ROBOT_LIFE_CPP_HAS_CUDA
  int count = 0;
  const auto err = cudaGetDeviceCount(&count);
  if (err != cudaSuccess) {
    info.available = false;
    info.message = cudaGetErrorString(err);
    return info;
  }

  info.available = count > 0;
  info.device_count = count;
  info.message = count > 0 ? "CUDA runtime detected" : "No CUDA devices detected";

  for (int i = 0; i < count; ++i) {
    cudaDeviceProp prop{};
    if (cudaGetDeviceProperties(&prop, i) != cudaSuccess) {
      continue;
    }
    CudaDeviceInfo dev{};
    dev.index = i;
    dev.name = prop.name;
    dev.total_memory_bytes = static_cast<std::size_t>(prop.totalGlobalMem);
    dev.multiprocessor_count = prop.multiProcessorCount;
    dev.major = prop.major;
    dev.minor = prop.minor;
    info.devices.push_back(std::move(dev));
  }
#else
  info.available = false;
  info.message = "Built without CUDA toolkit";
#endif
  return info;
}

}  // namespace robot_life_cpp::runtime
