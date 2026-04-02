#include "robot_life_cpp/root/deepstream_backend_cli.hpp"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

#include "robot_life_cpp/bridge/deepstream_protocol.hpp"
#include "robot_life_cpp/root/cli_shared.hpp"
#include "robot_life_cpp/perception/deepstream_graph.hpp"
#include "robot_life_cpp/perception/deepstream_runner.hpp"
#include "robot_life_cpp/runtime/runtime_tuning.hpp"

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

bool has_flag(std::span<const std::string> args, const std::string& flag) {
  return std::find(args.begin(), args.end(), flag) != args.end();
}

void maybe_write_app_config(
    const std::string& path,
    const perception::DeepStreamExecutionPlan& plan) {
  if (path.empty()) {
    return;
  }
  std::ofstream out(path);
  if (!out.good()) {
    std::cerr << "[graph-plan] failed_to_write_app_config path=" << path << "\n";
    return;
  }
  out << perception::render_deepstream_app_config(plan);
  std::cerr << "[graph-plan] wrote_app_config path=" << path << "\n";
}

void print_execution_plan(const perception::DeepStreamExecutionPlan& plan) {
  std::cerr << "[graph-plan] name=" << plan.graph_name
            << " branches=" << plan.branches.size()
            << " share_preprocess=" << (plan.share_preprocess ? "true" : "false")
            << " share_tracker=" << (plan.share_tracker ? "true" : "false")
            << " valid=" << (perception::deepstream_execution_plan_valid(plan) ? "true" : "false")
            << "\n";
  for (const auto& branch : plan.branches) {
    std::cerr << "[graph-plan] branch=" << branch.name
              << " enabled=" << (branch.enabled ? "true" : "false")
              << " plugin=" << branch.plugin
              << " stage=" << branch.binding_stage
              << " device=" << branch.device
              << " model=" << branch.model_config_path.string()
              << " model_exists=" << (branch.model_config_exists ? "true" : "false")
              << " shared_tracker=" << (branch.uses_shared_tracker ? "true" : "false")
              << "\n";
  }
  for (const auto& error : plan.errors) {
    std::cerr << "[graph-plan] error=" << error << "\n";
  }
}

void configure_graph(perception::DeepStreamFourVisionGraph* graph, std::span<const std::string> args) {
  if (graph == nullptr) {
    return;
  }
  graph->set_max_detections_per_frame(
      static_cast<std::size_t>(std::max(1, parse_int_arg(args, "--max-detections-per-frame", 4))));
  graph->set_share_preprocess(!has_flag(args, "--no-share-preprocess"));
  graph->set_share_tracker(!has_flag(args, "--no-share-tracker"));

  const auto face_interval = parse_int_arg(args, "--face-interval", 1);
  const auto pose_interval = parse_int_arg(args, "--pose-interval", 2);
  const auto motion_interval = parse_int_arg(args, "--motion-interval", 1);
  const auto scene_interval = parse_int_arg(args, "--scene-interval", 3);
  graph->set_branch_interval(perception::DeepStreamBranchId::Face, face_interval);
  graph->set_branch_interval(perception::DeepStreamBranchId::PoseGesture, pose_interval);
  graph->set_branch_interval(perception::DeepStreamBranchId::Motion, motion_interval);
  graph->set_branch_interval(perception::DeepStreamBranchId::SceneObject, scene_interval);

  if (has_flag(args, "--disable-face")) {
    graph->set_branch_enabled(perception::DeepStreamBranchId::Face, false);
  }
  if (has_flag(args, "--disable-pose")) {
    graph->set_branch_enabled(perception::DeepStreamBranchId::PoseGesture, false);
  }
  if (has_flag(args, "--disable-motion")) {
    graph->set_branch_enabled(perception::DeepStreamBranchId::Motion, false);
  }
  if (has_flag(args, "--disable-scene")) {
    graph->set_branch_enabled(perception::DeepStreamBranchId::SceneObject, false);
  }
}

void print_graph_summary(const perception::DeepStreamFourVisionGraph& graph) {
  const auto stats = graph.stats();
  std::cout << "[graph] name=" << stats.graph_name
            << " frames=" << stats.frames_ingested
            << " detections=" << stats.detections_emitted
            << " dropped_cap=" << stats.detections_dropped_due_to_cap
            << " disabled_hits=" << stats.disabled_branch_hits
            << " sampled_hits=" << stats.sampled_branch_hits
            << " enabled_branches=" << stats.enabled_branch_count << "\n";
  for (const auto& branch : stats.branches) {
    std::cout << "[graph] branch=" << branch.name
              << " enabled=" << (branch.enabled ? "true" : "false")
              << " seen=" << branch.frames_seen
              << " selected=" << branch.frames_selected
              << " skipped_disabled=" << branch.frames_skipped_disabled
              << " skipped_sampling=" << branch.frames_skipped_sampling
              << " emitted=" << branch.detections_emitted
              << " last_frame=" << branch.last_frame_index
              << " last_source=" << branch.last_source
              << " last_event=" << branch.last_event_type
              << "\n";
  }
}

}  // namespace

int deepstream_backend(std::span<const std::string> args) {
  const int frames = std::max(1, parse_int_arg(args, "--frames", 16));
  const int interval_ms = std::max(1, parse_int_arg(args, "--interval-ms", 10));
  const auto source = parse_string_arg(args, "--source", "deepstream_mock_camera");
  const auto mode = parse_string_arg(args, "--mode", "mock");
  const auto deepstream_app = parse_string_arg(args, "--deepstream-app", "");
  const auto write_app_config = parse_string_arg(args, "--write-app-config", "");
  const auto metadata_path = parse_string_arg(args, "--metadata-path", "");
  const auto graph_config_path =
      parse_string_arg(args, "--graph-config", "configs/deepstream_4vision.yaml");
  const auto runtime_tuning_path =
      parse_string_arg(args, "--runtime-tuning", default_runtime_tuning_path().string());
  perception::DeepStreamGraphConfig graph_config{};
  std::string config_error{};
  if (!perception::load_deepstream_graph_config(graph_config_path, &graph_config, &config_error)) {
    std::cerr << "[graph] config_load_failed path=" << graph_config_path
              << " error=" << config_error << "\n";
    graph_config = perception::default_deepstream_graph_config();
  }
  runtime::RuntimeTuningStore tuning_store{runtime_tuning_path};
  std::string tuning_error{};
  if (!tuning_store.load("linux_deepstream_4vision", &tuning_error)) {
    std::cerr << "[graph] tuning_load_failed path=" << runtime_tuning_path
              << " error=" << tuning_error << "\n";
  } else if (tuning_store.current().has_value()) {
    runtime::apply_runtime_tuning_to_graph(*tuning_store.current(), &graph_config);
  }
  perception::DeepStreamFourVisionGraph graph{graph_config};
  configure_graph(&graph, args);
  const auto plan = perception::build_deepstream_execution_plan(graph.config(), graph_config_path);
  print_execution_plan(plan);
  maybe_write_app_config(write_app_config, plan);

  const bool real_mode = mode == "real";
  if (real_mode && !perception::deepstream_execution_plan_valid(plan)) {
    std::cout << bridge::encode_health_line({.state = "failed", .detail = "real execution plan invalid"}) << "\n";
    std::cout.flush();
    return 2;
  }
  const auto warmup_detail = real_mode
                                 ? ("real runtime requested; validated execution plan; app=" +
                                    (deepstream_app.empty() ? std::string{"unset"} : deepstream_app) +
                                    " metadata=" +
                                    (metadata_path.empty() ? std::string{"unset"} : metadata_path))
                                 : "mock pipeline warming";

  std::cout << bridge::encode_health_line({.state = "starting", .detail = "backend process boot"}) << "\n";
  std::cout.flush();
  std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));

  std::cout << bridge::encode_health_line({.state = "warming", .detail = warmup_detail}) << "\n";
  std::cout.flush();
  std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));

  perception::DeepStreamRunnerRequest request{};
  request.frames = frames;
  request.interval_ms = interval_ms;
  request.source = source;
  request.mode = mode;
  request.deepstream_app = deepstream_app;
  request.write_app_config = write_app_config;
  request.metadata_path = metadata_path;

  auto runner = perception::make_deepstream_runner(mode);
  if (runner == nullptr) {
    std::cout << bridge::encode_health_line({.state = "failed", .detail = "runner not available"}) << "\n";
    std::cout.flush();
    return 4;
  }
  const int exit_code = runner->run(request, &graph, plan);
  print_graph_summary(graph);
  return exit_code;
}

}  // namespace robot_life_cpp::root
