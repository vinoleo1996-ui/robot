#include <iostream>

#include "robot_life_cpp/runtime/profile_registry.hpp"

namespace robot_life_cpp::root {

void print_profiles(const std::string& catalog_path) {
  runtime::ProfileRegistry registry{catalog_path};
  if (!registry.load()) {
    std::cout << "profiles: load failed: " << registry.error_message() << "\n";
    return;
  }
  std::cout << "profiles: default=" << registry.default_profile();
  for (const auto& profile : registry.profile_names()) {
    std::cout << ' ' << profile;
  }
  std::cout << "\n";
}

}  // namespace robot_life_cpp::root
