#include "robot_life_cpp/perception/registry.hpp"

#include <algorithm>

#include "robot_life_cpp/perception/deepstream_process_backend.hpp"

namespace robot_life_cpp::perception {

bool BackendRegistry::register_factory(BackendDescriptor descriptor, BackendFactory factory) {
  if (descriptor.name.empty() || !factory || has_backend(descriptor.name)) {
    return false;
  }
  entries_.emplace_back(std::move(descriptor), std::move(factory));
  return true;
}

bool BackendRegistry::has_backend(const std::string& name) const {
  return std::any_of(entries_.begin(), entries_.end(), [&](const auto& entry) {
    return entry.first.name == name;
  });
}

std::unique_ptr<Backend> BackendRegistry::create(const std::string& name, std::string* error) const {
  const auto it = std::find_if(entries_.begin(), entries_.end(), [&](const auto& entry) {
    return entry.first.name == name;
  });
  if (it == entries_.end()) {
    if (error != nullptr) {
      *error = "backend not registered: " + name;
    }
    return nullptr;
  }
  return it->second();
}

std::vector<BackendDescriptor> BackendRegistry::descriptors() const {
  std::vector<BackendDescriptor> result{};
  result.reserve(entries_.size());
  for (const auto& entry : entries_) {
    result.push_back(entry.first);
  }
  return result;
}

BackendRegistry make_default_backend_registry() {
  BackendRegistry registry{};
  registry.register_factory(
      {.name = "native", .transport = "inproc", .requires_gpu = false},
      [] { return make_null_backend("native", "native development backend placeholder"); });
  registry.register_factory(
      {.name = "deepstream", .transport = "ipc", .requires_gpu = true},
      [] { return std::make_unique<DeepStreamProcessBackend>(); });
  return registry;
}

}  // namespace robot_life_cpp::perception
