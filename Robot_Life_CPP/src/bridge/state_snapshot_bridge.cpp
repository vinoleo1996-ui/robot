#include "robot_life_cpp/bridge/state_snapshot_bridge.hpp"

#include <sstream>

namespace robot_life_cpp::bridge {

namespace {
std::string json_escape(const std::string& value) {
  std::ostringstream oss;
  for (const auto ch : value) {
    switch (ch) {
      case '\\':
        oss << "\\\\";
        break;
      case '\"':
        oss << "\\\"";
        break;
      case '\n':
        oss << "\\n";
        break;
      case '\r':
        oss << "\\r";
        break;
      case '\t':
        oss << "\\t";
        break;
      default:
        oss << ch;
        break;
    }
  }
  return oss.str();
}
}  // namespace

void StateSnapshotBridge::publish(runtime::RuntimeSnapshot snapshot) {
  std::lock_guard<std::mutex> lock(mu_);
  latest_ = std::move(snapshot);
}

runtime::RuntimeSnapshot StateSnapshotBridge::latest() const {
  std::lock_guard<std::mutex> lock(mu_);
  return latest_;
}

std::string StateSnapshotBridge::latest_json() const {
  const auto snap = latest();
  std::ostringstream oss;
  oss << "{";
  oss << "\"running\":" << (snap.running ? "true" : "false") << ",";
  oss << "\"now_mono_s\":" << snap.now_mono_s << ",";
  oss << "\"pending_events\":" << snap.pending_events << ",";
  oss << "\"stable_events_last_tick\":" << snap.stable_events_last_tick << ",";
  oss << "\"scene_candidates_last_tick\":" << snap.scene_candidates_last_tick;
  if (snap.last_decision.has_value()) {
    oss << ",\"last_decision\":{";
    oss << "\"decision_id\":\"" << json_escape(snap.last_decision->decision_id) << "\",";
    oss << "\"trace_id\":\"" << json_escape(snap.last_decision->trace_id) << "\",";
    oss << "\"target_behavior\":\"" << json_escape(snap.last_decision->target_behavior) << "\",";
    oss << "\"mode\":\"" << common::to_string(snap.last_decision->mode) << "\",";
    oss << "\"priority\":\"" << common::to_string(snap.last_decision->priority) << "\"";
    oss << "}";
  } else {
    oss << ",\"last_decision\":null";
  }
  oss << "}";
  return oss.str();
}

}  // namespace robot_life_cpp::bridge
