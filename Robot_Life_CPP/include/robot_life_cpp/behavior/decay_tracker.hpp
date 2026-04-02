#pragma once

#include <random>
#include <string>
#include <unordered_map>
#include <vector>

namespace robot_life_cpp::behavior {

class BehaviorDecayTracker {
 public:
  BehaviorDecayTracker(
      double decay_window_s = 300.0,
      int max_decay_count = 5,
      double min_strength = 0.3,
      double silent_probability_base = 0.3);

  std::pair<double, bool> evaluate(const std::string& scene_type, const std::string& target_id);
  void record(const std::string& scene_type, const std::string& target_id);
  void reset();

 private:
  std::string key_for(const std::string& scene_type, const std::string& target_id) const;
  void prune(const std::string& key, double now);
  static double now_mono();

  double decay_window_s_;
  int max_decay_count_;
  double min_strength_;
  double silent_probability_base_;
  std::unordered_map<std::string, std::vector<double>> history_;
  std::mt19937_64 rng_;
};

}  // namespace robot_life_cpp::behavior
