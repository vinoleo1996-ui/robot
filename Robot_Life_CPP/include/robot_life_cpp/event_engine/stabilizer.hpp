#pragma once

#include <optional>
#include <string>
#include <unordered_map>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct StabilizerRules {
  int debounce_count{2};
  double debounce_window_s{0.3};
  double cooldown_s{1.0};
  double hysteresis_threshold{0.7};
  double hysteresis_transition_high{0.85};
  double hysteresis_transition_low{0.6};
  double dedup_window_s{0.5};
  int default_ttl_ms{3000};
};

class EventStabilizer {
 public:
  explicit EventStabilizer(StabilizerRules rules = {});

  std::optional<common::StableEvent> process(
      const common::RawEvent& raw_event,
      double now_mono_s = common::now_mono());

  void reset();
  void reset_for_key(const std::string& cooldown_key);

 private:
  struct DebounceState {
    int count{0};
    double first_seen_at{0.0};
  };

  struct HysteresisState {
    bool active{false};
    double last_confidence{0.0};
    double last_seen_at{0.0};
  };

  bool check_debounce(const std::string& key, double now);
  bool check_hysteresis(const std::string& key, double confidence, double now);
  bool check_dedup(const common::RawEvent& raw_event, double now);
  bool check_cooldown(const std::string& key, double now);
  std::string dedup_signature(const common::RawEvent& raw_event) const;
  void gc(double now);

  StabilizerRules rules_;
  std::unordered_map<std::string, DebounceState> debounce_state_{};
  std::unordered_map<std::string, HysteresisState> hysteresis_state_{};
  std::unordered_map<std::string, double> cooldown_state_{};
  std::unordered_map<std::string, double> dedup_state_{};
  std::uint64_t gc_calls_{0};
};

}  // namespace robot_life_cpp::event_engine
