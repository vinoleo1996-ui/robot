#pragma once

#include <memory>
#include <string>

#include "robot_life_cpp/perception/registry.hpp"

namespace robot_life_cpp::runtime {

class PipelineFactory {
 public:
  PipelineFactory();

  perception::BackendRegistry& mutable_registry();
  const perception::BackendRegistry& registry() const;
  std::string backend_name_for_profile(const std::string& profile_name) const;
  std::unique_ptr<perception::Backend> create_for_profile(
      const std::string& profile_name,
      std::string* error = nullptr) const;

 private:
  perception::BackendRegistry registry_;
};

}  // namespace robot_life_cpp::runtime
