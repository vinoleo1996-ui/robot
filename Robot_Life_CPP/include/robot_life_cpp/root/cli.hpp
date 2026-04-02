#pragma once

#include <span>
#include <string>

namespace robot_life_cpp::root {

int doctor(std::span<const std::string> args);
int detector_status(std::span<const std::string> args);
int run(std::span<const std::string> args);
int run_live(std::span<const std::string> args);
int ui_demo(std::span<const std::string> args);
int ui_slow(std::span<const std::string> args);
int slow_consistency(std::span<const std::string> args);
int deepstream_backend(std::span<const std::string> args);

int dispatch_cli(std::span<const std::string> argv);
std::string version();

}  // namespace robot_life_cpp::root
