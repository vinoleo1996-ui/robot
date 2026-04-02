#pragma once

#include <string>

namespace robot_life_cpp::event_engine {

struct PolicyDecision {
  std::string response_level{"normal"};
  bool approved{true};
};

PolicyDecision make_default_policy_decision();

}  // namespace robot_life_cpp::event_engine
