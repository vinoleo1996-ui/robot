#include "robot_life_cpp/behavior/decay_tracker.hpp"

#include <algorithm>
#include <chrono>

namespace robot_life_cpp::behavior {

BehaviorDecayTracker::BehaviorDecayTracker(
    double decay_window_s,
    int max_decay_count,
    double min_strength,
    double silent_probability_base)
    : decay_window_s_(std::max(1.0, decay_window_s)),
      max_decay_count_(std::max(1, max_decay_count)),
      min_strength_(std::clamp(min_strength, 0.0, 1.0)),
      silent_probability_base_(std::clamp(silent_probability_base, 0.0, 1.0)),
      rng_(std::random_device{}()) {}

std::pair<double, bool> BehaviorDecayTracker::evaluate(
    const std::string& scene_type, const std::string& target_id) {
  const auto key = key_for(scene_type, target_id);
  const auto now = now_mono();
  prune(key, now);
  const auto count = static_cast<double>(history_[key].size());
  const auto decay_ratio = std::min(count / static_cast<double>(max_decay_count_), 1.0);
  const auto strength = 1.0 - (1.0 - min_strength_) * decay_ratio;
  const auto silent_probability = std::clamp(silent_probability_base_ + decay_ratio * 0.4, 0.0, 1.0);
  std::uniform_real_distribution<double> dist(0.0, 1.0);
  const bool use_voice = dist(rng_) > silent_probability;
  return {strength, use_voice};
}

void BehaviorDecayTracker::record(const std::string& scene_type, const std::string& target_id) {
  const auto key = key_for(scene_type, target_id);
  const auto now = now_mono();
  prune(key, now);
  history_[key].push_back(now);
}

void BehaviorDecayTracker::reset() { history_.clear(); }

std::string BehaviorDecayTracker::key_for(const std::string& scene_type, const std::string& target_id) const {
  return scene_type + ":" + (target_id.empty() ? "__any__" : target_id);
}

void BehaviorDecayTracker::prune(const std::string& key, double now) {
  const auto cutoff = now - decay_window_s_;
  auto& series = history_[key];
  series.erase(std::remove_if(series.begin(), series.end(),
                              [cutoff](double ts) { return ts <= cutoff; }),
               series.end());
}

double BehaviorDecayTracker::now_mono() {
  using clock = std::chrono::steady_clock;
  return std::chrono::duration<double>(clock::now().time_since_epoch()).count();
}

}  // namespace robot_life_cpp::behavior
