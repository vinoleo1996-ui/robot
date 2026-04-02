#pragma once

#include <string>
#include <unordered_map>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::event_engine {

class EventBuilder {
 public:
  explicit EventBuilder(
      std::unordered_map<std::string, common::EventPriority> event_priorities = {});

  common::RawEvent build(
      const common::DetectionResult& detection,
      std::optional<common::EventPriority> priority = std::nullopt,
      int ttl_ms = 3000) const;

 private:
  static std::string canonical_event_type(const std::string& event_type);
  static common::EventPriority default_event_priority(const std::string& event_type);

  std::unordered_map<std::string, common::EventPriority> event_priorities_{};
};

}  // namespace robot_life_cpp::event_engine
