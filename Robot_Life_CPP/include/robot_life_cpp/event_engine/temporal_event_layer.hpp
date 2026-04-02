#pragma once

#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

struct TemporalLayerSnapshot {
  std::vector<std::string> active_gaze_targets{};
  std::vector<std::string> active_attention_targets{};
};

class TemporalEventLayer {
 public:
  explicit TemporalEventLayer(double gaze_hold_ttl_s = 2.5, double attention_memory_ttl_s = 3.0);

  std::vector<common::StableEvent> process(
      const common::StableEvent& stable_event,
      double now_mono_s = common::now_mono());

  TemporalLayerSnapshot snapshot(double now_mono_s = common::now_mono());

 private:
  static std::string target_id_from_payload(const common::Payload& payload);
  static common::StableEvent derive_event(
      const common::StableEvent& base,
      const std::string& event_type,
      double now_mono_s);
  void prune(double now_mono_s);

  double gaze_hold_ttl_s_{2.5};
  double attention_memory_ttl_s_{3.0};
  std::unordered_map<std::string, double> active_gaze_targets_{};
  std::unordered_map<std::string, double> active_attention_targets_{};
};

}  // namespace robot_life_cpp::event_engine

