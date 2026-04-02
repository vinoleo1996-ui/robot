#include "robot_life_cpp/runtime/profile_registry.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>

namespace robot_life_cpp::runtime {

namespace {
std::string trim_copy(const std::string& input) {
  std::string value = input;
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(),
                           [](unsigned char c) { return !std::isspace(c); }));
  value.erase(std::find_if(value.rbegin(), value.rend(),
                           [](unsigned char c) { return !std::isspace(c); })
                  .base(),
              value.end());
  return value;
}
}  // namespace

ProfileRegistry::ProfileRegistry(std::string catalog_path)
    : catalog_path_(std::move(catalog_path)) {}

bool ProfileRegistry::load() {
  default_profile_.clear();
  profile_names_.clear();
  error_message_.clear();

  std::ifstream fin(catalog_path_);
  if (!fin.good()) {
    error_message_ = "cannot open profile catalog: " + catalog_path_;
    return false;
  }

  bool in_profiles = false;
  std::string line{};
  while (std::getline(fin, line)) {
    const auto trimmed = trim_copy(line);
    if (trimmed.empty() || trimmed.rfind('#', 0) == 0) {
      continue;
    }
    if (trimmed == "profiles:") {
      in_profiles = true;
      continue;
    }
    if (!in_profiles) {
      if (trimmed.rfind("default_profile:", 0) == 0) {
        auto value = trim_copy(trimmed.substr(std::string("default_profile:").size()));
        if (!value.empty()) {
          default_profile_ = std::move(value);
        }
      }
      continue;
    }
    if (line.rfind("  ", 0) != 0 || line.rfind("    ", 0) == 0) {
      continue;
    }
    if (trimmed.back() != ':') {
      continue;
    }
    auto key = trimmed.substr(0, trimmed.size() - 1);
    if (!key.empty()) {
      profile_names_.push_back(std::move(key));
    }
  }

  if (profile_names_.empty()) {
    error_message_ = "no profiles found in catalog";
    return false;
  }
  if (default_profile_.empty()) {
    error_message_ = "default_profile missing in catalog";
    return false;
  }
  if (!has_profile(default_profile_)) {
    error_message_ = "default_profile not found in catalog: " + default_profile_;
    return false;
  }
  return true;
}

const std::string& ProfileRegistry::default_profile() const { return default_profile_; }

const std::vector<std::string>& ProfileRegistry::profile_names() const {
  return profile_names_;
}

const std::string& ProfileRegistry::catalog_path() const { return catalog_path_; }

bool ProfileRegistry::has_profile(const std::string& name) const {
  return std::find(profile_names_.begin(), profile_names_.end(), name) != profile_names_.end();
}

std::string ProfileRegistry::error_message() const { return error_message_; }

}  // namespace robot_life_cpp::runtime
