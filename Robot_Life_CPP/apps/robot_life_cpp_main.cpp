#include <iostream>
#include <string>
#include <vector>

#include "robot_life_cpp/bridge/state_snapshot_bridge.hpp"
#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/migration/module_catalog.hpp"
#include "robot_life_cpp/root/cli.hpp"
#include "robot_life_cpp/runtime/cuda_probe.hpp"
#include "robot_life_cpp/runtime/live_loop.hpp"
#include "robot_life_cpp/runtime/profile_registry.hpp"

namespace {
robot_life_cpp::common::RawEvent make_event(
    std::string event_type,
    double confidence,
    std::string source,
    robot_life_cpp::common::EventPriority priority) {
  robot_life_cpp::common::RawEvent event{};
  event.event_id = robot_life_cpp::common::new_id();
  event.trace_id = robot_life_cpp::common::new_id();
  event.event_type = std::move(event_type);
  event.priority = priority;
  event.timestamp_monotonic = robot_life_cpp::common::now_mono();
  event.confidence = confidence;
  event.source = std::move(source);
  event.cooldown_key = event.event_type + ":" + event.source;
  event.payload = {{"confidence", std::to_string(confidence)}};
  return event;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc > 1) {
    std::vector<std::string> args{};
    args.reserve(static_cast<std::size_t>(argc - 1));
    for (int i = 1; i < argc; ++i) {
      args.emplace_back(argv[i]);
    }
    return robot_life_cpp::root::dispatch_cli(args);
  }

  auto cuda = robot_life_cpp::runtime::probe_cuda_runtime();
  std::cout << "[runtime] CUDA available: " << (cuda.available ? "yes" : "no")
            << ", devices=" << cuda.device_count << ", message=" << cuda.message << "\n";
  for (const auto& dev : cuda.devices) {
    std::cout << "[runtime] GPU[" << dev.index << "] " << dev.name
              << " sm=" << dev.major << "." << dev.minor
              << " mp=" << dev.multiprocessor_count
              << " vram=" << (dev.total_memory_bytes / (1024 * 1024)) << "MiB\n";
  }
  std::cout << "[migration] implemented_modules="
            << robot_life_cpp::migration::implemented_module_count() << "/"
            << robot_life_cpp::migration::total_module_count() << "\n";

#ifdef ROBOT_LIFE_CPP_PROFILE_CATALOG_PATH
  robot_life_cpp::runtime::ProfileRegistry profile_registry{
      ROBOT_LIFE_CPP_PROFILE_CATALOG_PATH};
  if (profile_registry.load()) {
    std::cout << "[profiles] catalog=" << profile_registry.catalog_path()
              << " default=" << profile_registry.default_profile() << " names=";
    for (const auto& name : profile_registry.profile_names()) {
      std::cout << name << " ";
    }
    std::cout << "\n";
  } else {
    std::cout << "[profiles] load_failed: " << profile_registry.error_message() << "\n";
  }
#endif

  robot_life_cpp::runtime::LiveLoop loop{};
  std::vector<robot_life_cpp::common::RawEvent> demo_events{};
  demo_events.push_back(make_event("face_detected", 0.91, "camera", robot_life_cpp::common::EventPriority::P1));
  demo_events.push_back(make_event("speech_activity", 0.85, "audio", robot_life_cpp::common::EventPriority::P1));
  demo_events.push_back(make_event("gesture_wave", 0.93, "camera", robot_life_cpp::common::EventPriority::P0));
  demo_events.push_back(make_event("motion_spike", 0.70, "camera", robot_life_cpp::common::EventPriority::P2));

  for (const auto& event : demo_events) {
    auto e1 = event;
    auto e2 = event;
    e1.event_id = robot_life_cpp::common::new_id();
    e2.event_id = robot_life_cpp::common::new_id();
    e1.timestamp_monotonic = robot_life_cpp::common::now_mono();
    e2.timestamp_monotonic = e1.timestamp_monotonic + 0.03;
    loop.ingest(std::move(e1));
    loop.ingest(std::move(e2));
    loop.run_for_ticks(3);
  }

  auto snap = loop.snapshot();
  robot_life_cpp::bridge::StateSnapshotBridge debug_bridge{};
  debug_bridge.publish(snap);
  std::cout << "[runtime] pending=" << snap.pending_events
            << " stable_last_tick=" << snap.stable_events_last_tick
            << " scenes_last_tick=" << snap.scene_candidates_last_tick << "\n";
  if (snap.last_decision.has_value()) {
    std::cout << "[decision] behavior=" << snap.last_decision->target_behavior
              << " mode=" << robot_life_cpp::common::to_string(snap.last_decision->mode)
              << " priority=" << robot_life_cpp::common::to_string(snap.last_decision->priority)
              << " reason=" << snap.last_decision->reason << "\n";
  } else {
    std::cout << "[decision] none\n";
  }
  std::cout << "[debug_bridge] " << debug_bridge.latest_json() << "\n";
  return 0;
}
