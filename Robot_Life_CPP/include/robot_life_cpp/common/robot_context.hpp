#pragma once

#include <deque>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace robot_life_cpp::common {

struct RecentInteraction {
  std::string behavior_id;
  std::optional<std::string> target_id;
  double ended_at{0.0};
  std::string status;
};

class RobotContextStore {
 public:
  explicit RobotContextStore(
      std::string mode = "demo",
      bool do_not_disturb = false,
      std::optional<double> battery_level = std::nullopt,
      int max_recent_interactions = 8);

  void set_mode(const std::string& mode);
  void set_do_not_disturb(bool enabled);
  void mark_active_behavior(const std::optional<std::string>& behavior_id,
                            const std::optional<std::string>& status);
  void set_interaction_context(const std::optional<std::string>& target_id,
                               const std::optional<std::string>& episode_id,
                               const std::optional<std::string>& intent);
  void push_finished_interaction(const RecentInteraction& item);

  std::unordered_map<std::string, std::string> snapshot() const;

 private:
  static double now_mono();

  std::string mode_;
  bool do_not_disturb_;
  std::optional<double> battery_level_;
  bool speaking_{false};
  bool listening_{false};
  bool moving_{false};
  std::optional<std::string> active_behavior_id_;
  std::optional<std::string> active_behavior_status_;
  std::optional<std::string> current_interaction_target_;
  std::optional<std::string> current_interaction_episode_id_;
  std::optional<std::string> current_intent_;
  double updated_at_{0.0};
  std::deque<RecentInteraction> recent_interactions_;
  std::size_t max_recent_interactions_{8};
};

}  // namespace robot_life_cpp::common
