#pragma once

#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "robot_life_cpp/perception/base.hpp"

namespace robot_life_cpp::perception {

struct BackendDescriptor {
  std::string name;
  std::string transport;
  bool requires_gpu{false};
};

using BackendFactory = std::function<std::unique_ptr<Backend>()>;

class BackendRegistry {
 public:
  bool register_factory(BackendDescriptor descriptor, BackendFactory factory);
  bool has_backend(const std::string& name) const;
  std::unique_ptr<Backend> create(const std::string& name, std::string* error = nullptr) const;
  std::vector<BackendDescriptor> descriptors() const;

 private:
  std::vector<std::pair<BackendDescriptor, BackendFactory>> entries_{};
};

BackendRegistry make_default_backend_registry();

}  // namespace robot_life_cpp::perception
