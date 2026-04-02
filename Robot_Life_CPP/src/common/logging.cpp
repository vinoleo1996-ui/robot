#include "robot_life_cpp/common/logging.hpp"

#include <algorithm>
#include <atomic>
#include <cctype>

namespace robot_life_cpp::common {

namespace {
std::atomic<LogLevel> g_level{LogLevel::Info};

std::string upper_copy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  return value;
}
}  // namespace

LogLevel parse_log_level(const std::string& level_name) {
  const auto normalized = upper_copy(level_name);
  if (normalized == "DEBUG") {
    return LogLevel::Debug;
  }
  if (normalized == "WARNING" || normalized == "WARN") {
    return LogLevel::Warning;
  }
  if (normalized == "ERROR") {
    return LogLevel::Error;
  }
  return LogLevel::Info;
}

void configure_logging(const std::string& level_name) {
  g_level.store(parse_log_level(level_name));
}

LogLevel current_log_level() { return g_level.load(); }

}  // namespace robot_life_cpp::common
