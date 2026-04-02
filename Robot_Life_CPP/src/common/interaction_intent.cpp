#include "robot_life_cpp/common/interaction_intent.hpp"

#include <algorithm>
#include <cctype>
#include <unordered_map>

namespace robot_life_cpp::common {

namespace {
std::string upper_copy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  return value;
}
}  // namespace

std::string intent_for_state(const std::optional<std::string>& state_name) {
  static const std::unordered_map<std::string, std::string> kStateToIntent{
      {"IDLE", "idle_scan"},
      {"NOTICED_HUMAN", "ack_presence"},
      {"MUTUAL_ATTENTION", "establish_attention"},
      {"ENGAGING", "maintain_engagement"},
      {"ONGOING_INTERACTION", "maintain_engagement"},
      {"RECOVERY", "graceful_disengage"},
      {"SAFETY_OVERRIDE", "safety_override"},
  };
  const auto normalized = upper_copy(state_name.value_or("IDLE"));
  const auto it = kStateToIntent.find(normalized);
  if (it == kStateToIntent.end()) {
    return "idle_scan";
  }
  return it->second;
}

std::string intent_from_snapshot(
    const std::unordered_map<std::string, std::string>& snapshot) {
  const auto intent_it = snapshot.find("intent");
  if (intent_it != snapshot.end() && !intent_it->second.empty()) {
    return intent_it->second;
  }
  const auto state_it = snapshot.find("state");
  if (state_it == snapshot.end()) {
    return "idle_scan";
  }
  return intent_for_state(state_it->second);
}

}  // namespace robot_life_cpp::common
