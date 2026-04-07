#include "robot_life_cpp/perception/deepstream_process_backend.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <sys/select.h>
#include <unistd.h>

#include "robot_life_cpp/bridge/deepstream_protocol.hpp"
#include "robot_life_cpp/perception/deepstream_adapter.hpp"

namespace robot_life_cpp::perception {

namespace {
constexpr std::size_t kMaxBufferedDetections = 128;

std::string quote_shell_arg(const std::string& value) {
  std::string quoted{"'"};
  for (const char ch : value) {
    if (ch == '\'') {
      quoted += "'\\''";
    } else {
      quoted.push_back(ch);
    }
  }
  quoted.push_back('\'');
  return quoted;
}

std::filesystem::path main_binary_path() {
#ifdef ROBOT_LIFE_CPP_MAIN_BIN_PATH
  return std::filesystem::path{ROBOT_LIFE_CPP_MAIN_BIN_PATH};
#else
  return std::filesystem::path{"robot_life_cpp_main"};
#endif
}

std::filesystem::path resolve_graph_config_path() {
  const char* configured = std::getenv("ROBOT_LIFE_CPP_DEEPSTREAM_GRAPH_CONFIG");
  if (configured != nullptr && *configured != '\0') {
    return std::filesystem::path{configured};
  }
  return std::filesystem::path{"configs/deepstream_4vision.yaml"};
}

std::filesystem::path resolve_metadata_path() {
  const char* configured = std::getenv("ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH");
  if (configured != nullptr && *configured != '\0') {
    return std::filesystem::path{configured};
  }
  return std::filesystem::path{"/tmp/robot_life_cpp_deepstream_metadata.ndjson"};
}

std::filesystem::path resolve_generated_app_config_path() {
  const char* configured = std::getenv("ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH");
  if (configured != nullptr && *configured != '\0') {
    return std::filesystem::path{configured};
  }
  return std::filesystem::path{"/tmp/robot_life_cpp_deepstream_app.txt"};
}

std::string resolve_requested_mode() {
  const char* configured = std::getenv("ROBOT_LIFE_CPP_DEEPSTREAM_MODE");
  if (configured == nullptr || *configured == '\0') {
    return "auto";
  }
  return configured;
}

bool host_supports_real_deepstream() {
#if defined(__linux__)
  return true;
#else
  return false;
#endif
}

bool is_executable_file(const std::filesystem::path& path) {
  if (path.empty() || !std::filesystem::exists(path) || std::filesystem::is_directory(path)) {
    return false;
  }
  return ::access(path.c_str(), X_OK) == 0;
}

std::filesystem::path find_executable_on_path(const std::string& name) {
  const char* raw_path = std::getenv("PATH");
  if (raw_path == nullptr || *raw_path == '\0') {
    return {};
  }

  std::stringstream stream{raw_path};
  std::string entry{};
  while (std::getline(stream, entry, ':')) {
    if (entry.empty()) {
      continue;
    }
    const auto candidate = std::filesystem::path{entry} / name;
    if (is_executable_file(candidate)) {
      return candidate;
    }
  }
  return {};
}

std::filesystem::path resolve_deepstream_app_path() {
  const char* explicit_app = std::getenv("DEEPSTREAM_APP");
  if (explicit_app != nullptr && *explicit_app != '\0') {
    const auto candidate = std::filesystem::path{explicit_app};
    if (is_executable_file(candidate)) {
      return candidate;
    }
  }

  const auto on_path = find_executable_on_path("deepstream-app");
  if (!on_path.empty()) {
    return on_path;
  }

  const std::vector<std::filesystem::path> defaults = {
      "/opt/nvidia/deepstream/deepstream/bin/deepstream-app",
      "/opt/nvidia/deepstream/deepstream-8.0/bin/deepstream-app",
      "/usr/bin/deepstream-app",
  };
  for (const auto& candidate : defaults) {
    if (is_executable_file(candidate)) {
      return candidate;
    }
  }
  return {};
}

std::string build_backend_command(
    const std::string& mode,
    const std::filesystem::path& graph_config,
    const std::filesystem::path& deepstream_app,
    const std::filesystem::path& metadata_path,
    const std::filesystem::path& generated_app_config_path) {
  std::string command = quote_shell_arg(main_binary_path().string()) +
                        " deepstream-backend --frames 32 --interval-ms 5 --mode " + mode +
                        " --graph-config " + quote_shell_arg(graph_config.string());
  if (!deepstream_app.empty()) {
    command += " --deepstream-app " + quote_shell_arg(deepstream_app.string());
  }
  if (!metadata_path.empty()) {
    command += " --metadata-path " + quote_shell_arg(metadata_path.string());
  }
  if (!generated_app_config_path.empty()) {
    command += " --write-app-config " + quote_shell_arg(generated_app_config_path.string());
  }
  return command;
}

std::string fallback_reason(
    const std::string& requested_mode,
    const std::filesystem::path& graph_config,
    const std::filesystem::path& deepstream_app,
    const std::filesystem::path& metadata_path) {
  if (requested_mode == "mock") {
    return "requested mock mode";
  }
  if (!host_supports_real_deepstream()) {
    return "host_not_linux";
  }
  if (graph_config.empty() || !std::filesystem::exists(graph_config)) {
    return "missing_graph_config";
  }
  if (deepstream_app.empty()) {
    return "deepstream_app_not_found";
  }
  if (metadata_path.empty() || metadata_path.parent_path().empty() ||
      !std::filesystem::exists(metadata_path.parent_path())) {
    return "metadata_path_unavailable";
  }
  return "auto_fallback";
}

DeepStreamAdapter& adapter_instance() {
  static DeepStreamAdapter adapter{};
  return adapter;
}
}  // namespace

DeepStreamLaunchSpec resolve_deepstream_launch_spec(std::string requested_mode_override) {
  DeepStreamLaunchSpec spec{};
  spec.requested_mode = requested_mode_override.empty() ? resolve_requested_mode() : std::move(requested_mode_override);
  spec.graph_config_path = resolve_graph_config_path();
  spec.deepstream_app_path = resolve_deepstream_app_path();
  spec.metadata_path = resolve_metadata_path();
  spec.generated_app_config_path = resolve_generated_app_config_path();
  spec.real_runtime_available = host_supports_real_deepstream() &&
                                std::filesystem::exists(spec.graph_config_path) &&
                                !spec.deepstream_app_path.empty() &&
                                !spec.metadata_path.empty() &&
                                !spec.metadata_path.parent_path().empty() &&
                                std::filesystem::exists(spec.metadata_path.parent_path());

  if (spec.requested_mode == "mock") {
    spec.resolved_mode = "mock";
    spec.detail = fallback_reason(
        spec.requested_mode, spec.graph_config_path, spec.deepstream_app_path, spec.metadata_path);
  } else if (spec.requested_mode == "real") {
    if (spec.real_runtime_available) {
      spec.resolved_mode = "real";
      spec.detail = "real DeepStream runtime selected";
    } else {
      spec.resolved_mode = "mock";
      spec.detail = "real requested but unavailable: " +
                    fallback_reason(
                        spec.requested_mode, spec.graph_config_path, spec.deepstream_app_path, spec.metadata_path);
    }
  } else {
    if (spec.real_runtime_available) {
      spec.resolved_mode = "real";
      spec.detail = "auto selected real DeepStream runtime";
    } else {
      spec.resolved_mode = "mock";
      spec.detail = "auto selected mock backend: " +
                    fallback_reason(
                        spec.requested_mode, spec.graph_config_path, spec.deepstream_app_path, spec.metadata_path);
    }
  }

  spec.command = build_backend_command(
      spec.resolved_mode,
      spec.graph_config_path,
      spec.deepstream_app_path,
      spec.metadata_path,
      spec.generated_app_config_path);
  return spec;
}

DeepStreamLaunchSpec resolve_deepstream_launch_spec() {
  return resolve_deepstream_launch_spec({});
}

DeepStreamProcessBackend::DeepStreamProcessBackend(
    std::string requested_mode_override,
    bool require_real_runtime)
    : requested_mode_override_(std::move(requested_mode_override)),
      require_real_runtime_(require_real_runtime) {}

DeepStreamProcessBackend::~DeepStreamProcessBackend() { stop(); }

std::string DeepStreamProcessBackend::backend_id() const { return "deepstream"; }

bool DeepStreamProcessBackend::start() {
  stop();
  manual_stop_ = false;
  queue_.clear();
  launch_spec_ = resolve_deepstream_launch_spec(requested_mode_override_);
  if (require_real_runtime_ && launch_spec_.resolved_mode != "real") {
    health_ = {.healthy = false,
               .state = "failed",
               .detail = "real DeepStream runtime required, got " + launch_spec_.resolved_mode +
                         ": " + launch_spec_.detail};
    stats_.running = false;
    return false;
  }
  return spawn_process();
}

void DeepStreamProcessBackend::stop() {
  manual_stop_ = true;
  if (pipe_ != nullptr) {
    pclose(pipe_);
    pipe_ = nullptr;
  }
  queue_.clear();
  stats_.running = false;
  health_ = {.healthy = false, .state = "stopped", .detail = "backend stopped"};
}

std::vector<common::DetectionResult> DeepStreamProcessBackend::poll(std::size_t max_items) {
  refresh_pipe();
  std::vector<common::DetectionResult> batch{};
  const auto limit = std::min(max_items, queue_.size());
  batch.reserve(limit);
  for (std::size_t i = 0; i < limit; ++i) {
    batch.push_back(std::move(queue_.front()));
    queue_.pop_front();
  }
  if (!batch.empty()) {
    ++stats_.delivered_batches;
    stats_.delivered_detections += batch.size();
  }
  return batch;
}

BackendHealth DeepStreamProcessBackend::health() const { return health_; }

BackendStats DeepStreamProcessBackend::stats() const { return stats_; }

const DeepStreamLaunchSpec& DeepStreamProcessBackend::launch_spec() const { return launch_spec_; }

bool DeepStreamProcessBackend::spawn_process() {
  pipe_ = popen(launch_spec_.command.c_str(), "r");
  if (pipe_ == nullptr) {
    health_ = {.healthy = false, .state = "failed", .detail = std::strerror(errno)};
    stats_.running = false;
    return false;
  }
  health_ = {.healthy = false,
             .state = "starting",
             .detail = "deepstream backend process spawned (" + launch_spec_.resolved_mode + ", " +
                       launch_spec_.detail + ")"};
  stats_.running = true;
  refresh_pipe();
  return true;
}

void DeepStreamProcessBackend::refresh_pipe() {
  if (pipe_ == nullptr) {
    if (!manual_stop_) {
      spawn_process();
    }
    return;
  }

  const int fd = fileno(pipe_);
  if (fd < 0) {
    health_ = {.healthy = false, .state = "failed", .detail = "invalid pipe descriptor"};
    stats_.running = false;
    return;
  }

  while (true) {
    fd_set readfds;
    FD_ZERO(&readfds);
    FD_SET(fd, &readfds);
    timeval timeout{};
    timeout.tv_sec = 0;
    timeout.tv_usec = 0;
    const int ready = select(fd + 1, &readfds, nullptr, nullptr, &timeout);
    if (ready <= 0 || !FD_ISSET(fd, &readfds)) {
      break;
    }

    std::array<char, 4096> buffer{};
    if (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe_) == nullptr) {
      pclose(pipe_);
      pipe_ = nullptr;
      stats_.running = false;
      if (manual_stop_) {
        health_ = {.healthy = false, .state = "stopped", .detail = "backend pipe closed"};
      } else {
        health_ = {.healthy = false, .state = "restarting", .detail = "backend pipe closed, reconnecting"};
      }
      break;
    }

    std::string line{buffer.data()};
    while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
      line.pop_back();
    }
    if (line.empty()) {
      continue;
    }

    const auto envelope = bridge::parse_deepstream_line(line);
    if (!envelope.has_value()) {
      continue;
    }
    if (envelope->kind == bridge::DeepStreamEnvelope::Kind::Health && envelope->health.has_value()) {
      health_ = {.healthy = envelope->health->state == "ready" || envelope->health->state == "warming" ||
                              envelope->health->state == "starting",
                 .state = envelope->health->state,
                 .detail = envelope->health->detail};
      continue;
    }
    if (envelope->kind == bridge::DeepStreamEnvelope::Kind::Detection && envelope->detection.has_value()) {
      auto adapted = adapter_instance().adapt_detection(*envelope);
      if (!adapted.has_value()) {
        continue;
      }
      if (queue_.size() >= kMaxBufferedDetections) {
        queue_.pop_front();
      }
      queue_.push_back(std::move(*adapted));
      if (!health_.healthy) {
        health_ = {.healthy = true, .state = "ready", .detail = "receiving detections"};
      }
    }
  }
}

}  // namespace robot_life_cpp::perception
