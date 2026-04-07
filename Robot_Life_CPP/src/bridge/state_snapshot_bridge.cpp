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
  oss << "\"scene_candidates_last_tick\":" << snap.scene_candidates_last_tick << ",";
  oss << "\"executions_last_tick\":" << snap.executions_last_tick << ",";
  oss << "\"execution_history_size\":" << snap.execution_history_size;
  if (snap.last_decision.has_value()) {
    oss << ",\"last_decision\":{";
    oss << "\"decision_id\":\"" << json_escape(snap.last_decision->decision_id) << "\",";
    oss << "\"trace_id\":\"" << json_escape(snap.last_decision->trace_id) << "\",";
    oss << "\"scene_type\":";
    if (snap.last_decision->scene_type.has_value()) {
      oss << "\"" << json_escape(*snap.last_decision->scene_type) << "\"";
    } else {
      oss << "null";
    }
    oss << ",";
    oss << "\"target_id\":";
    if (snap.last_decision->target_id.has_value()) {
      oss << "\"" << json_escape(*snap.last_decision->target_id) << "\"";
    } else {
      oss << "null";
    }
    oss << ",";
    oss << "\"target_behavior\":\"" << json_escape(snap.last_decision->target_behavior) << "\",";
    oss << "\"mode\":\"" << common::to_string(snap.last_decision->mode) << "\",";
    oss << "\"priority\":\"" << common::to_string(snap.last_decision->priority) << "\"";
    oss << "}";
  } else {
    oss << ",\"last_decision\":null";
  }
  if (snap.last_execution.has_value()) {
    oss << ",\"last_execution\":{";
    oss << "\"execution_id\":\"" << json_escape(snap.last_execution->execution_id) << "\",";
    oss << "\"trace_id\":\"" << json_escape(snap.last_execution->trace_id) << "\",";
    oss << "\"behavior_id\":\"" << json_escape(snap.last_execution->behavior_id) << "\",";
    oss << "\"status\":\"" << json_escape(snap.last_execution->status) << "\",";
    oss << "\"interrupted\":" << (snap.last_execution->interrupted ? "true" : "false") << ",";
    oss << "\"degraded\":" << (snap.last_execution->degraded ? "true" : "false");
    oss << "}";
  } else {
    oss << ",\"last_execution\":null";
  }
  oss << "}";
  return oss.str();
}

}  // namespace robot_life_cpp::bridge
