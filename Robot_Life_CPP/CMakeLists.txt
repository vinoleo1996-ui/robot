cmake_minimum_required(VERSION 3.20)
project(RobotLifeCPP VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(ROBOT_LIFE_CPP_BUILD_TESTS "Build tests" ON)
option(ROBOT_LIFE_CPP_ENABLE_CUDA "Enable CUDA integration when toolkit exists" ON)
option(ROBOT_LIFE_CPP_REQUIRE_CUDA "Fail configure when CUDA toolkit is unavailable" OFF)

find_package(Threads REQUIRED)
if(ROBOT_LIFE_CPP_ENABLE_CUDA)
  find_package(CUDAToolkit QUIET)
endif()

if(ROBOT_LIFE_CPP_REQUIRE_CUDA AND NOT CUDAToolkit_FOUND)
  message(FATAL_ERROR "ROBOT_LIFE_CPP_REQUIRE_CUDA=ON but CUDAToolkit not found")
endif()

add_library(robot_life_core STATIC
  src/common/schemas.cpp
  src/common/visual_contract.cpp
  src/bridge/state_snapshot_bridge.cpp
  src/bridge/deepstream_protocol.cpp
  src/event_engine/stabilizer.cpp
  src/event_engine/scene_aggregator.cpp
  src/event_engine/arbitrator.cpp
  src/runtime/live_loop.cpp
  src/runtime/cuda_probe.cpp
  src/runtime/profile_registry.cpp
)

target_include_directories(robot_life_core
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_options(robot_life_core
  PRIVATE
    -Wall
    -Wextra
    -Wpedantic
    -Wconversion
    -Wshadow
    -Wnon-virtual-dtor
)

target_link_libraries(robot_life_core PRIVATE Threads::Threads)

if(CUDAToolkit_FOUND)
  target_link_libraries(robot_life_core PRIVATE CUDA::cudart)
  target_compile_definitions(robot_life_core PUBLIC ROBOT_LIFE_CPP_HAS_CUDA=1)
else()
  target_compile_definitions(robot_life_core PUBLIC ROBOT_LIFE_CPP_HAS_CUDA=0)
endif()

add_executable(robot_life_cpp_main
  apps/robot_life_cpp_main.cpp
)
target_link_libraries(robot_life_cpp_main PRIVATE robot_life_core)
target_compile_definitions(robot_life_cpp_main PRIVATE
  ROBOT_LIFE_CPP_PROFILE_CATALOG_PATH="${CMAKE_CURRENT_SOURCE_DIR}/configs/profile_catalog.yaml"
)

add_library(robot_life_migration STATIC
  src/migration/module_catalog.cpp
)
target_include_directories(robot_life_migration
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_compile_options(robot_life_migration PRIVATE -Wall -Wextra -Wpedantic)

add_library(robot_life_modules OBJECT
  src/root/__init__.cpp
  src/root/app.cpp
  src/root/cli_shared.cpp
  src/root/cli_doctor.cpp
  src/root/cli_deepstream_backend.cpp
  src/root/cli_live.cpp
  src/root/cli_slow_scene.cpp
  src/root/profiles.cpp
  src/common/__init__.cpp
  src/common/contracts.cpp
  src/common/cuda_runtime.cpp
  src/common/logging.cpp
  src/common/config.cpp
  src/common/payload_contracts.cpp
  src/common/state_machine.cpp
  src/common/robot_context.cpp
  src/common/tracing.cpp
  src/common/interaction_intent.cpp
  src/behavior/__init__.cpp
  src/behavior/behavior_registry.cpp
  src/behavior/bt_nodes.cpp
  src/behavior/bt_runtime.cpp
  src/behavior/decay_tracker.cpp
  src/behavior/executor.cpp
  src/behavior/manager.cpp
  src/behavior/resources.cpp
  src/behavior/safety_guard.cpp
  src/event_engine/__init__.cpp
  src/event_engine/arbitration_runtime.cpp
  src/event_engine/policy_layer.cpp
  src/event_engine/builder.cpp
  src/event_engine/cooldown_manager.cpp
  src/event_engine/decision_queue.cpp
  src/event_engine/entity_tracker.cpp
  src/event_engine/temporal_event_layer.cpp
  src/runtime/__init__.cpp
  src/runtime/event_injector.cpp
  src/runtime/execution_manager.cpp
  src/runtime/execution_support.cpp
  src/runtime/health_monitor.cpp
  src/runtime/interaction_intent.cpp
  src/runtime/life_state.cpp
  src/runtime/load_shedder.cpp
  src/runtime/long_task_coordinator.cpp
  src/runtime/pipeline_factory.cpp
  src/runtime/scene_context.cpp
  src/runtime/scene_coordinator.cpp
  src/runtime/scene_ops.cpp
  src/runtime/sources.cpp
  src/runtime/target_governor.cpp
  src/runtime/telemetry.cpp
  src/runtime/runtime_tuning.cpp
  src/runtime/ui_demo.cpp
  src/runtime/ui_service.cpp
  src/runtime/ui_slow_scene.cpp
  src/perception/__init__.cpp
  src/perception/base.cpp
  src/perception/deepstream_adapter.cpp
  src/perception/deepstream_export_contract.cpp
  src/perception/deepstream_exporter.cpp
  src/perception/deepstream_graph.cpp
  src/perception/deepstream_process_backend.cpp
  src/perception/deepstream_runner.cpp
  src/perception/frame_dispatch.cpp
  src/perception/registry.cpp
  src/perception/adapters/__init__.cpp
  src/perception/adapters/audio_adapter.cpp
  src/perception/adapters/gguf_qwen_adapter.cpp
  src/perception/adapters/insightface_adapter.cpp
  src/perception/adapters/mediapipe_adapter.cpp
  src/perception/adapters/mediapipe_pose_adapter.cpp
  src/perception/adapters/motion_adapter.cpp
  src/perception/adapters/panns_whisper_audio_adapter.cpp
  src/perception/adapters/qwen_adapter.cpp
  src/perception/adapters/whisper_adapter.cpp
  src/perception/adapters/yamnet_audio_adapter.cpp
  src/perception/adapters/yolo_pose_adapter.cpp
  src/slow_scene/__init__.cpp
  src/slow_scene/queue.cpp
  src/slow_scene/schema.cpp
  src/slow_scene/service.cpp
  src/slow_scene/snapshot.cpp
  src/slow_scene/worker.cpp
)
target_include_directories(robot_life_modules
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_compile_options(robot_life_modules PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(robot_life_modules PRIVATE Threads::Threads)
target_compile_definitions(robot_life_modules PUBLIC
  ROBOT_LIFE_CPP_MAIN_BIN_PATH="${CMAKE_CURRENT_BINARY_DIR}/robot_life_cpp_main"
)

target_link_libraries(robot_life_cpp_main PRIVATE robot_life_migration)
target_link_libraries(robot_life_cpp_main PRIVATE robot_life_modules)

if(ROBOT_LIFE_CPP_BUILD_TESTS)
  enable_testing()
  add_executable(test_core tests/test_core.cpp)
  target_link_libraries(test_core PRIVATE robot_life_core robot_life_modules robot_life_migration)
  target_compile_options(test_core PRIVATE -UNDEBUG)
  add_test(NAME test_core COMMAND test_core)
endif()
