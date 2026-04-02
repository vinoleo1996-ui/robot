#include "robot_life_cpp/root/cli.hpp"

#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

namespace robot_life_cpp::root {

int dispatch_cli(std::span<const std::string> argv) {
  using Handler = int (*)(std::span<const std::string>);
  static const std::unordered_map<std::string, Handler> kHandlers{
      {"doctor", doctor},
      {"detector-status", detector_status},
      {"run", run},
      {"run-live", run_live},
      {"ui-demo", ui_demo},
      {"ui-slow", ui_slow},
      {"slow-consistency", slow_consistency},
      {"deepstream-backend", deepstream_backend},
  };

  if (argv.empty()) {
    std::cout << "available commands: doctor detector-status run run-live ui-demo ui-slow slow-consistency deepstream-backend\n";
    return 0;
  }
  const auto& cmd = argv.front();
  const auto it = kHandlers.find(cmd);
  if (it == kHandlers.end()) {
    std::cerr << "unknown command: " << cmd << "\n";
    return 2;
  }
  return it->second(argv.subspan(1));
}

}  // namespace robot_life_cpp::root
