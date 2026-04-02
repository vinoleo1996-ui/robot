#pragma once

#include <string>
#include <vector>

namespace robot_life_cpp::runtime {

class ProfileRegistry {
 public:
  explicit ProfileRegistry(std::string catalog_path);

  bool load();
  const std::string& default_profile() const;
  const std::vector<std::string>& profile_names() const;
  const std::string& catalog_path() const;
  bool has_profile(const std::string& name) const;
  std::string error_message() const;

 private:
  std::string catalog_path_;
  std::string default_profile_{};
  std::vector<std::string> profile_names_{};
  std::string error_message_;
};

}  // namespace robot_life_cpp::runtime
