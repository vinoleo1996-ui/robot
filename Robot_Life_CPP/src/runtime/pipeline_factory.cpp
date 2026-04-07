#include "robot_life_cpp/runtime/pipeline_factory.hpp"

#include <memory>

#include "robot_life_cpp/perception/deepstream_process_backend.hpp"

namespace robot_life_cpp::runtime {

PipelineFactory::PipelineFactory() : registry_(perception::make_default_backend_registry()) {}

perception::BackendRegistry& PipelineFactory::mutable_registry() { return registry_; }

const perception::BackendRegistry& PipelineFactory::registry() const { return registry_; }

std::string PipelineFactory::backend_name_for_profile(const std::string& profile_name) const {
  if (profile_name == "linux_deepstream_4vision" || profile_name == "deepstream_prod") {
    return "deepstream";
  }
  if (profile_name == "mac_debug_native" || profile_name == "linux_cpu_fallback_safe" ||
      profile_name == "cpu_debug" || profile_name == "fallback_safe") {
    return "native";
  }
  return {};
}

std::unique_ptr<perception::Backend> PipelineFactory::create_for_profile(
    const std::string& profile_name,
    std::string* error) const {
  if (profile_name == "deepstream_prod") {
    return std::make_unique<perception::DeepStreamProcessBackend>("real", true);
  }
  if (profile_name == "linux_deepstream_4vision") {
    return std::make_unique<perception::DeepStreamProcessBackend>("auto", false);
  }
  const auto backend_name = backend_name_for_profile(profile_name);
  if (backend_name.empty()) {
    if (error != nullptr) {
      *error = "unsupported profile for pipeline factory: " + profile_name;
    }
    return nullptr;
  }
  return registry_.create(backend_name, error);
}

}  // namespace robot_life_cpp::runtime
