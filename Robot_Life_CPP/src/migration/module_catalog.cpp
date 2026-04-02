#include "robot_life_cpp/migration/module_catalog.hpp"

namespace robot_life_cpp::migration {

const std::vector<ModuleMapping>& module_catalog() {
  static const std::vector<ModuleMapping> kCatalog = {
      ModuleMapping{"robot_life/__init__.py", "src/root/__init__.cpp", "root", true},
      ModuleMapping{"robot_life/app.py", "src/root/app.cpp", "root", true},
      ModuleMapping{"robot_life/behavior/__init__.py", "src/behavior/__init__.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/behavior_registry.py", "src/behavior/behavior_registry.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/bt_nodes.py", "src/behavior/bt_nodes.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/bt_runtime.py", "src/behavior/bt_runtime.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/decay_tracker.py", "src/behavior/decay_tracker.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/executor.py", "src/behavior/executor.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/manager.py", "src/behavior/manager.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/resources.py", "src/behavior/resources.cpp", "behavior", true},
      ModuleMapping{"robot_life/behavior/safety_guard.py", "src/behavior/safety_guard.cpp", "behavior", true},
      ModuleMapping{"robot_life/cli_doctor.py", "src/root/cli_doctor.cpp", "root", true},
      ModuleMapping{"robot_life/cli_live.py", "src/root/cli_live.cpp", "root", true},
      ModuleMapping{"robot_life/cli_shared.py", "src/root/cli_shared.cpp", "root", true},
      ModuleMapping{"robot_life/cli_slow_scene.py", "src/root/cli_slow_scene.cpp", "root", true},
      ModuleMapping{"robot_life/common/__init__.py", "src/common/__init__.cpp", "common", true},
      ModuleMapping{"robot_life/common/config.py", "src/common/config.cpp", "common", true},
      ModuleMapping{"robot_life/common/contracts.py", "src/common/contracts.cpp", "common", true},
      ModuleMapping{"robot_life/common/cuda_runtime.py", "src/common/cuda_runtime.cpp", "common", true},
      ModuleMapping{"robot_life/common/interaction_intent.py", "src/common/interaction_intent.cpp", "common", true},
      ModuleMapping{"robot_life/common/logging.py", "src/common/logging.cpp", "common", true},
      ModuleMapping{"robot_life/common/payload_contracts.py", "src/common/payload_contracts.cpp", "common", true},
      ModuleMapping{"robot_life/common/robot_context.py", "src/common/robot_context.cpp", "common", true},
      ModuleMapping{"robot_life/common/schemas.py", "src/common/schemas.cpp", "common", true},
      ModuleMapping{"robot_life/common/state_machine.py", "src/common/state_machine.cpp", "common", true},
      ModuleMapping{"robot_life/common/tracing.py", "src/common/tracing.cpp", "common", true},
      ModuleMapping{"robot_life/event_engine/__init__.py", "src/event_engine/__init__.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/arbitration_runtime.py", "src/event_engine/arbitration_runtime.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/arbitrator.py", "src/event_engine/arbitrator.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/builder.py", "src/event_engine/builder.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/cooldown_manager.py", "src/event_engine/cooldown_manager.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/decision_queue.py", "src/event_engine/decision_queue.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/entity_tracker.py", "src/event_engine/entity_tracker.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/policy_layer.py", "src/event_engine/policy_layer.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/scene_aggregator.py", "src/event_engine/scene_aggregator.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/stabilizer.py", "src/event_engine/stabilizer.cpp", "event_engine", true},
      ModuleMapping{"robot_life/event_engine/temporal_event_layer.py", "src/event_engine/temporal_event_layer.cpp", "event_engine", true},
      ModuleMapping{"robot_life/perception/__init__.py", "src/perception/__init__.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/__init__.py", "src/perception/adapters/__init__.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/audio_adapter.py", "src/perception/adapters/audio_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/gguf_qwen_adapter.py", "src/perception/adapters/gguf_qwen_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/insightface_adapter.py", "src/perception/adapters/insightface_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/mediapipe_adapter.py", "src/perception/adapters/mediapipe_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/mediapipe_pose_adapter.py", "src/perception/adapters/mediapipe_pose_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/motion_adapter.py", "src/perception/adapters/motion_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/panns_whisper_audio_adapter.py", "src/perception/adapters/panns_whisper_audio_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/qwen_adapter.py", "src/perception/adapters/qwen_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/whisper_adapter.py", "src/perception/adapters/whisper_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/yamnet_audio_adapter.py", "src/perception/adapters/yamnet_audio_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/adapters/yolo_pose_adapter.py", "src/perception/adapters/yolo_pose_adapter.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/base.py", "src/perception/base.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/frame_dispatch.py", "src/perception/frame_dispatch.cpp", "perception", true},
      ModuleMapping{"robot_life/perception/registry.py", "src/perception/registry.cpp", "perception", true},
      ModuleMapping{"robot_life/profiles.py", "src/root/profiles.cpp", "root", true},
      ModuleMapping{"robot_life/runtime/__init__.py", "src/runtime/__init__.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/event_injector.py", "src/runtime/event_injector.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/execution_manager.py", "src/runtime/execution_manager.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/execution_support.py", "src/runtime/execution_support.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/health_monitor.py", "src/runtime/health_monitor.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/interaction_intent.py", "src/runtime/interaction_intent.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/life_state.py", "src/runtime/life_state.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/live_loop.py", "src/runtime/live_loop.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/load_shedder.py", "src/runtime/load_shedder.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/long_task_coordinator.py", "src/runtime/long_task_coordinator.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/pipeline_factory.py", "src/runtime/pipeline_factory.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/scene_context.py", "src/runtime/scene_context.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/scene_coordinator.py", "src/runtime/scene_coordinator.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/scene_ops.py", "src/runtime/scene_ops.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/sources.py", "src/runtime/sources.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/target_governor.py", "src/runtime/target_governor.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/telemetry.py", "src/runtime/telemetry.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/ui_demo.py", "src/runtime/ui_demo.cpp", "runtime", true},
      ModuleMapping{"robot_life/runtime/ui_slow_scene.py", "src/runtime/ui_slow_scene.cpp", "runtime", true},
      ModuleMapping{"robot_life/slow_scene/__init__.py", "src/slow_scene/__init__.cpp", "slow_scene", true},
      ModuleMapping{"robot_life/slow_scene/queue.py", "src/slow_scene/queue.cpp", "slow_scene", true},
      ModuleMapping{"robot_life/slow_scene/schema.py", "src/slow_scene/schema.cpp", "slow_scene", true},
      ModuleMapping{"robot_life/slow_scene/service.py", "src/slow_scene/service.cpp", "slow_scene", true},
      ModuleMapping{"robot_life/slow_scene/snapshot.py", "src/slow_scene/snapshot.cpp", "slow_scene", true},
      ModuleMapping{"robot_life/slow_scene/worker.py", "src/slow_scene/worker.cpp", "slow_scene", true},
  };
  return kCatalog;
}

std::size_t implemented_module_count() {
  std::size_t count = 0;
  for (const auto& item : module_catalog()) {
    if (item.implemented) {
      count += 1;
    }
  }
  return count;
}

std::size_t total_module_count() { return module_catalog().size(); }

}  // namespace robot_life_cpp::migration
