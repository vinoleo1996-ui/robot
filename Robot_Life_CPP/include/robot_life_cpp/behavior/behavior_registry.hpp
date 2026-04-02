#pragma once

#include <string>
#include <unordered_map>
#include <vector>

namespace robot_life_cpp::behavior {

struct BehaviorTemplate {
  std::string behavior_id;
  std::vector<std::string> nodes{};
  bool resumable{true};
  bool optional_speech{false};
  std::unordered_map<std::string, std::string> metadata{};
};

class BehaviorRegistry {
 public:
  BehaviorRegistry();

  BehaviorTemplate get(const std::string& behavior_id) const;

 private:
  std::unordered_map<std::string, BehaviorTemplate> templates_;
};

}  // namespace robot_life_cpp::behavior
