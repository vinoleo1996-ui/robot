#include "robot_life_cpp/root/cli.hpp"

#include <algorithm>
#include <chrono>
#include <iostream>
#include <thread>
#include <vector>

#include "robot_life_cpp/bridge/state_snapshot_bridge.hpp"
#include "robot_life_cpp/common/schemas.hpp"
#include "robot_life_cpp/common/visual_contract.hpp"
#include "robot_life_cpp/root/cli_shared.hpp"
#include "robot_life_cpp/runtime/cuda_probe.hpp"
#include "robot_life_cpp/runtime/event_injector.hpp"
#include "robot_life_cpp/runtime/health_monitor.hpp"
#include "robot_life_cpp/runtime/load_shedder.hpp"
#include "robot_life_cpp/runtime/live_loop.hpp"
#include "robot_life_cpp/runtime/pipeline_factory.hpp"
#include "robot_life_cpp/runtime/runtime_tuning.hpp"
#include "robot_life_cpp/runtime/telemetry.hpp"
#include "robot_life_cpp/runtime/ui_demo.hpp"

namespace robot_life_cpp::root {

namespace {
std::string parse_string_arg(
    std::span<const std::string> args,
    const std::string& flag,
    std::string fallback) {
  for (std::size_t i = 0; i + 1 < args.size(); ++i) {
    if (args[i] == flag) {
      return args[i + 1];
    }
  }
  return fallback;
}

int parse_int_arg(std::span<const std::string> args, const std::string& flag, int fallback) {
  for (std::size_t i = 0; i + 1 < args.size(); ++i) {
    if (args[i] == flag) {
      return std::stoi(args[i + 1]);
    }
  }
  return fallback;
}

bool parse_bool_arg(std::span<const std::string> args, const std::string& flag, bool fallback) {
  for (std::size_t i = 0; i + 1 < args.size(); ++i) {
    if (args[i] == flag) {
      const auto& value = args[i + 1];
      return value == "1" || value == "true" || value == "yes" || value == "on";
    }
  }
  return fallback;
}

std::string host_platform_name() {
#if defined(__APPLE__)
  return "macos";
#elif defined(__linux__)
  return "linux";
#else
  return "unknown";
#endif
}

common::RawEvent make_event(
    const std::string& type,
    double confidence,
    common::EventPriority priority) {
  common::RawEvent event{};
  event.event_id = common::new_id();
  event.trace_id = common::new_id();
  event.event_type = type;
  event.priority = priority;
  event.timestamp_monotonic = common::now_mono();
  event.confidence = confidence;
  event.source = "cli_live";
  event.cooldown_key = type + ":default";
  event.payload = {{"confidence", std::to_string(confidence)}};
  return event;
}

common::DetectionResult make_detection(
    std::string detector,
    std::string event_type,
    std::string frame_id,
    std::string track_id) {
  common::DetectionResult detection{};
  detection.trace_id = common::new_id();
  detection.source = "cli_live";
  detection.detector = std::move(detector);
  detection.event_type = std::move(event_type);
  detection.timestamp = common::now_wall();
  detection.confidence = 0.9;
  detection.payload = {
      {std::string(common::visual_contract::KEY_CAMERA_ID), "front_cam"},
      {std::string(common::visual_contract::KEY_FRAME_ID), std::move(frame_id)},
      {std::string(common::visual_contract::KEY_TRACK_ID), std::move(track_id)},
      {std::string(common::visual_contract::KEY_BBOX), "10,20,100,120"},
  };
  return detection;
}

void print_health(const runtime::RuntimeHealthMonitor& monitor) {
  const auto snapshot = monitor.snapshot();
  std::cout << "[launcher] phase=" << monitor.phase_name() << " detail=" << snapshot.detail << "\n";
  for (const auto& component : snapshot.components) {
    std::cout << "[launcher] component=" << component.name
              << " healthy=" << (component.healthy ? "true" : "false")
              << " state=" << component.state
              << " detail=" << component.detail << "\n";
  }
}
}  // namespace

int run(std::span<const std::string> /*args*/) {
  runtime::LiveLoop loop{};
  loop.ingest(make_event("face_detected", 0.92, common::EventPriority::P1));
  loop.ingest(make_event("gesture_wave", 0.93, common::EventPriority::P0));
  loop.run_for_ticks(3);
  const auto snap = loop.snapshot();
  std::cout << "run complete: pending=" << snap.pending_events
            << " scenes=" << snap.scene_candidates_last_tick << "\n";
  return 0;
}

int run_live(std::span<const std::string> args) {
  const auto profile = parse_string_arg(args, "--profile", "mac_debug_native");
  const auto ticks = std::max(1, parse_int_arg(args, "--ticks", 4));
  const bool ui_enabled = parse_bool_arg(args, "--ui", false);
  const auto runtime_tuning_path =
      parse_string_arg(args, "--runtime-tuning", default_runtime_tuning_path().string());
  const bool reload_tuning = parse_bool_arg(args, "--reload-tuning", true);
  const auto ui_html_out =
      parse_string_arg(args, "--ui-html-out", "/tmp/robot_life_cpp_dashboard.html");
  const auto ui_json_out =
      parse_string_arg(args, "--ui-json-out", "/tmp/robot_life_cpp_dashboard.json");

  runtime::RuntimeHealthMonitor monitor{};
  monitor.set_phase(runtime::RuntimePhase::Starting, "launcher boot");
  monitor.update_component({"env", true, "ready", "local environment validated"});

  runtime::RuntimeTuningStore tuning_store{runtime_tuning_path};
  std::string tuning_error{};
  if (!tuning_store.load(profile, &tuning_error)) {
    monitor.update_component({"tuning", false, "failed", tuning_error});
    monitor.set_phase(runtime::RuntimePhase::Failed, "runtime tuning load failed");
    print_health(monitor);
    return 1;
  }
  monitor.update_component({"tuning", true, "ready", runtime_tuning_path});
  const auto& tuning = *tuning_store.current();

  runtime::PipelineFactory factory{};
  std::string error{};
  auto backend = factory.create_for_profile(profile, &error);
  if (backend == nullptr) {
    monitor.set_phase(runtime::RuntimePhase::Failed, error);
    print_health(monitor);
    return 2;
  }

  monitor.update_component({"backend", false, "starting", "spawning perception backend"});
  print_health(monitor);
  if (!backend->start()) {
    const auto health = backend->health();
    monitor.update_component({"backend", false, health.state, health.detail});
    monitor.set_phase(runtime::RuntimePhase::Failed, "backend start failed");
    print_health(monitor);
    return 3;
  }

  monitor.set_phase(runtime::RuntimePhase::Warming, "waiting for backend readiness");
  runtime::LiveLoop loop{
      tuning.live_loop,
      tuning.stabilizer,
      tuning.aggregator,
      tuning.arbitrator,
  };
  runtime::DetectionEventInjector injector{tuning.event_injector};
  auto active_injector_config = tuning.event_injector;
  runtime::AggregatingTelemetrySink telemetry{};
  runtime::RuntimeLoadShedder load_shedder{};
  bridge::StateSnapshotBridge debug_bridge{};
  std::vector<common::DetectionResult> preview_detections{};
  preview_detections.reserve(4);
  monitor.update_component({"core", true, "ready", "live loop initialized"});
  monitor.update_component({"ui", !ui_enabled, ui_enabled ? "starting" : "disabled",
                            ui_enabled ? "debug ui requested" : "debug ui skipped"});

  bool backend_ready = false;
  for (int i = 0; i < 30; ++i) {
    auto detections = backend->poll(16);
    const auto health = backend->health();
    monitor.update_component({"backend", health.healthy, health.state, health.detail});
    if (!detections.empty()) {
      injector.inject_into(&loop, detections, common::now_mono());
    }
    if (health.state == "ready" || !detections.empty()) {
      backend_ready = true;
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  if (!backend_ready && backend->backend_id() == "native") {
    std::vector<common::DetectionResult> bootstrap{};
    bootstrap.push_back(make_detection("native_face", "face_detected", "native-1", "person_track_native"));
    bootstrap.push_back(make_detection("native_pose", "pose_detected", "native-2", "person_track_native"));
    injector.inject_into(&loop, bootstrap, common::now_mono());
    monitor.update_component({"backend", true, "ready", "native bootstrap detections injected"});
    backend_ready = true;
  }

  if (!backend_ready) {
    monitor.set_phase(runtime::RuntimePhase::Degraded, "backend not ready within warmup window");
  } else {
    monitor.set_phase(runtime::RuntimePhase::Ready, "backend and core ready");
  }

  if (ui_enabled) {
    monitor.update_component({"ui", true, "ready", "debug snapshot bridge active"});
  }
  print_health(monitor);

  for (int i = 0; i < ticks; ++i) {
    bool reloaded = false;
    if (reload_tuning) {
      std::string reload_error{};
      if (!tuning_store.reload_if_changed(profile, &reloaded, &reload_error)) {
        monitor.update_component({"tuning", false, "failed", reload_error});
      } else if (reloaded) {
        const auto& current_tuning = *tuning_store.current();
        loop.reconfigure(
            current_tuning.live_loop,
            current_tuning.stabilizer,
            current_tuning.aggregator,
            current_tuning.arbitrator);
        injector.reconfigure(current_tuning.event_injector);
        monitor.update_component({"tuning", true, "reloaded", runtime_tuning_path});
      }
    }
    const auto poll_started = common::now_mono();
    auto detections = backend->poll(16);
    runtime::emit_stage_trace(
        &telemetry,
        common::new_id(),
        "backend_poll",
        "ok",
        {
            {"backend_id", backend->backend_id()},
            {"detections", std::to_string(detections.size())},
        },
        poll_started,
        common::now_mono());
    if (!detections.empty()) {
      preview_detections.assign(
          detections.begin(),
          detections.begin() + static_cast<std::ptrdiff_t>(std::min<std::size_t>(4, detections.size())));
    }
    if (!detections.empty()) {
      injector.inject_into(&loop, detections, common::now_mono());
    }
    const auto tick_snapshot_before = loop.snapshot();
    const auto tick_started = common::now_mono();
    loop.tick();
    runtime::emit_stage_trace(
        &telemetry,
        common::new_id(),
        "live_loop_tick",
        "ok",
        {
            {"pending_before", std::to_string(tick_snapshot_before.pending_events)},
        },
        tick_started,
        common::now_mono());

    const auto current_snapshot = loop.snapshot();
    const auto shed = load_shedder.decide(
        {.runtime = current_snapshot,
         .backend = backend->stats(),
         .ui_enabled = ui_enabled,
         .configured_max_events_per_batch = tuning_store.current()->event_injector.max_events_per_batch});
    auto injector_config = tuning_store.current()->event_injector;
    injector_config.max_events_per_batch =
        std::min<std::size_t>(injector_config.max_events_per_batch, shed.max_events_per_batch);
    if (injector_config.max_events_per_batch != active_injector_config.max_events_per_batch ||
        injector_config.dedupe_window_s != active_injector_config.dedupe_window_s ||
        injector_config.cooldown_window_s != active_injector_config.cooldown_window_s) {
      injector.reconfigure(injector_config);
      active_injector_config = injector_config;
    }
    monitor.update_component(
        {"load_shedder", shed.pressure == runtime::LoadPressure::Normal,
         runtime::to_string(shed.pressure), shed.reason});

    if (ui_enabled && shed.preview_enabled && (i % shed.preview_every_ticks) == 0) {
      const auto cuda = runtime::probe_cuda_runtime();
      runtime::DebugDashboardData dashboard{};
      dashboard.runtime = current_snapshot;
      dashboard.health = monitor.snapshot();
      dashboard.backend = backend->stats();
      dashboard.telemetry = telemetry.snapshot();
      dashboard.tuning = *tuning_store.current();
      dashboard.load_shed = shed;
      dashboard.preview_detections = preview_detections;
      dashboard.platform = host_platform_name();
      dashboard.gpu_summary =
          cuda.available ? ("cuda devices=" + std::to_string(cuda.device_count)) : cuda.message;
      runtime::write_debug_dashboard_files(dashboard, ui_html_out, ui_json_out);
    }
  }

  auto snap = loop.snapshot();
  debug_bridge.publish(snap);
  monitor.set_phase(runtime::RuntimePhase::Stopping, "launcher shutdown");
  print_health(monitor);
  backend->stop();
  monitor.update_component({"backend", false, "stopped", "backend stopped"});
  monitor.set_phase(runtime::RuntimePhase::Stopped, "launcher complete");
  print_health(monitor);
  std::cout << "[runtime] pending=" << snap.pending_events
            << " stable_last_tick=" << snap.stable_events_last_tick
            << " scenes_last_tick=" << snap.scene_candidates_last_tick << "\n";
  if (snap.last_decision.has_value()) {
    std::cout << "[decision] behavior=" << snap.last_decision->target_behavior
              << " mode=" << common::to_string(snap.last_decision->mode)
              << " priority=" << common::to_string(snap.last_decision->priority)
              << " reason=" << snap.last_decision->reason << "\n";
  } else {
    std::cout << "[decision] none\n";
  }
  if (ui_enabled) {
    std::cout << "[debug_bridge] " << debug_bridge.latest_json() << "\n";
    std::cout << "[ui] html=" << ui_html_out << " json=" << ui_json_out << "\n";
  }
  return monitor.phase() == runtime::RuntimePhase::Stopped ? 0 : 4;
}

int ui_demo(std::span<const std::string> args) {
  std::vector<std::string> forwarded{};
  forwarded.reserve(args.size() + 2);
  forwarded.emplace_back("--ui");
  forwarded.emplace_back("true");
  for (const auto& arg : args) {
    forwarded.push_back(arg);
  }
  return run_live(forwarded);
}

}  // namespace robot_life_cpp::root
