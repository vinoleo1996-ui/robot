#pragma once

#include <string>

namespace robot_life_cpp::common {

enum class LogLevel {
  Debug = 0,
  Info = 1,
  Warning = 2,
  Error = 3,
};

LogLevel parse_log_level(const std::string& level_name);
void configure_logging(const std::string& level_name = "INFO");
LogLevel current_log_level();

}  // namespace robot_life_cpp::common
