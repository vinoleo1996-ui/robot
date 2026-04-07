#pragma once

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/event_engine/builder.hpp"
#include "robot_life_cpp/event_engine/entity_tracker.hpp"
#include "robot_life_cpp/runtime/live_loop.hpp"

namespace robot_life_cpp::runtime {

struct EventInjectorConfig {
  double dedupe_window_s{0.15};
  double cooldown_window_s{0.05};
  std::size_t max_events_per_batch{64};
};

class DetectionEventInjector {
 public:
  explicit DetectionEventInjector(EventInjectorConfig config = {});
  void reconfigure(EventInjectorConfig config);

  std::vector<common::RawEvent> build_events(
      const std::vector<common::DetectionResult>& detections,
      double now_mono);

  std::size_t inject_into(
      LiveLoop* loop,
      const std::vector<common::DetectionResult>& detections,
      double now_mono);

 private:
  bool should_emit(const common::RawEvent& event, double now_mono);
  static std::string dedupe_signature(const common::RawEvent& event);

  EventInjectorConfig config_;
  event_engine::EventBuilder builder_{};
  event_engine::EntityTracker entity_tracker_{};
  std::unordered_map<std::string, double> last_emit_by_signature_{};
  std::unordered_map<std::string, double> last_emit_by_cooldown_key_{};
};

}  // namespace robot_life_cpp::runtime
