#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace robot_life_cpp::common::config {

struct RuntimeConfig {
  std::string project_root{"."};
  std::string log_level{"INFO"};
  bool trace_enabled{true};
  bool mock_drivers{true};
  std::vector<std::string> enabled_pipelines{};
};

struct AppConfig {
  RuntimeConfig runtime{};
};

namespace {
std::string trim(std::string value) {
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

std::unordered_map<std::string, std::string> load_yaml_like(const std::filesystem::path& path) {
  std::unordered_map<std::string, std::string> out{};
  std::ifstream fin(path);
  if (!fin.good()) {
    return out;
  }
  std::string line{};
  while (std::getline(fin, line)) {
    auto no_comment = line.substr(0, line.find('#'));
    auto pos = no_comment.find(':');
    if (pos == std::string::npos) {
      continue;
    }
    auto key = trim(no_comment.substr(0, pos));
    auto value = trim(no_comment.substr(pos + 1));
    if (!key.empty()) {
      out[key] = value;
    }
  }
  return out;
}

AppConfig load_app_config(const std::filesystem::path& path) {
  AppConfig cfg{};
  auto kv = load_yaml_like(path);
  if (auto it = kv.find("project_root"); it != kv.end() && !it->second.empty()) {
    cfg.runtime.project_root = it->second;
  }
  if (auto it = kv.find("log_level"); it != kv.end() && !it->second.empty()) {
    cfg.runtime.log_level = it->second;
  }
  if (auto it = kv.find("trace_enabled"); it != kv.end()) {
    cfg.runtime.trace_enabled = it->second == "true" || it->second == "1";
  }
  if (auto it = kv.find("mock_drivers"); it != kv.end()) {
    cfg.runtime.mock_drivers = it->second == "true" || it->second == "1";
  }
  return cfg;
}

}  // namespace robot_life_cpp::common::config
