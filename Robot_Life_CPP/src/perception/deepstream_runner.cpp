#include "robot_life_cpp/perception/deepstream_runner.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>

#include "robot_life_cpp/bridge/deepstream_protocol.hpp"

namespace robot_life_cpp::perception {

namespace {

enum class ChildExitState {
  Running,
  ExitedZero,
  ExitedNonZero,
  Signaled,
  Error,
};

struct ChildExitInfo {
  ChildExitState state{ChildExitState::Running};
  int code{0};
};

void maybe_write_app_config(const std::string& path, const DeepStreamExecutionPlan& plan) {
  if (path.empty()) {
    return;
  }
  std::ofstream out(path);
  if (!out.good()) {
    return;
  }
  out << render_deepstream_app_config(plan);
}

std::optional<pid_t> launch_deepstream_app(
    const std::string& deepstream_app,
    const std::string& app_config_path) {
  if (deepstream_app.empty() || app_config_path.empty()) {
    return std::nullopt;
  }

  const pid_t pid = fork();
  if (pid < 0) {
    return std::nullopt;
  }
  if (pid == 0) {
    const int devnull = open("/dev/null", O_WRONLY);
    if (devnull >= 0) {
      dup2(devnull, STDOUT_FILENO);
      dup2(devnull, STDERR_FILENO);
      close(devnull);
    }
    execl(deepstream_app.c_str(), deepstream_app.c_str(), "-c", app_config_path.c_str(), static_cast<char*>(nullptr));
    _exit(127);
  }
  return pid;
}

std::vector<std::string> read_metadata_lines(
    const std::filesystem::path& metadata_path,
    std::uintmax_t* offset) {
  std::vector<std::string> lines{};
  if (offset == nullptr || metadata_path.empty() || !std::filesystem::exists(metadata_path)) {
    return lines;
  }

  const auto size = std::filesystem::file_size(metadata_path);
  if (*offset > size) {
    *offset = 0;
  }

  std::ifstream in(metadata_path);
  if (!in.good()) {
    return lines;
  }
  in.seekg(static_cast<std::streamoff>(*offset), std::ios::beg);
  std::string line{};
  while (std::getline(in, line)) {
    if (!line.empty()) {
      lines.push_back(line);
    }
  }
  const auto end_pos = in.tellg();
  *offset = end_pos >= 0 ? static_cast<std::uintmax_t>(end_pos) : size;
  return lines;
}

ChildExitInfo poll_child_exit(std::optional<pid_t> pid) {
  if (!pid.has_value()) {
    return {.state = ChildExitState::Error, .code = 0};
  }
  int status = 0;
  const auto waited = waitpid(*pid, &status, WNOHANG);
  if (waited == 0) {
    return {.state = ChildExitState::Running, .code = 0};
  }
  if (waited < 0) {
    return {.state = ChildExitState::Error, .code = errno};
  }
  if (WIFEXITED(status)) {
    const int code = WEXITSTATUS(status);
    return {.state = code == 0 ? ChildExitState::ExitedZero : ChildExitState::ExitedNonZero, .code = code};
  }
  if (WIFSIGNALED(status)) {
    return {.state = ChildExitState::Signaled, .code = WTERMSIG(status)};
  }
  return {.state = ChildExitState::Error, .code = status};
}

std::string describe_child_exit(const ChildExitInfo& info) {
  switch (info.state) {
    case ChildExitState::Running:
      return "child still running";
    case ChildExitState::ExitedZero:
      return "deepstream-app exited with code 0";
    case ChildExitState::ExitedNonZero:
      return "deepstream-app exited with code " + std::to_string(info.code);
    case ChildExitState::Signaled:
      return "deepstream-app terminated by signal " + std::to_string(info.code);
    case ChildExitState::Error:
      return "waitpid failed with errno " + std::to_string(info.code);
  }
  return "unknown child exit state";
}

bool cleanup_deepstream_child(std::optional<pid_t> pid, int shutdown_timeout_ms, std::string* detail) {
  if (!pid.has_value()) {
    if (detail != nullptr) {
      *detail = "no child process";
    }
    return true;
  }

  const auto initial = poll_child_exit(pid);
  if (initial.state != ChildExitState::Running) {
    if (detail != nullptr) {
      *detail = describe_child_exit(initial);
    }
    return initial.state == ChildExitState::ExitedZero;
  }

  kill(*pid, SIGTERM);
  const int sleep_ms = 10;
  const int max_polls = std::max(1, shutdown_timeout_ms / sleep_ms);
  for (int i = 0; i < max_polls; ++i) {
    const auto exit = poll_child_exit(pid);
    if (exit.state != ChildExitState::Running) {
      if (detail != nullptr) {
        *detail = describe_child_exit(exit);
      }
      return exit.state == ChildExitState::ExitedZero ||
             (exit.state == ChildExitState::Signaled && exit.code == SIGTERM);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
  }

  kill(*pid, SIGKILL);
  int status = 0;
  waitpid(*pid, &status, 0);
  if (detail != nullptr) {
    *detail = "deepstream-app forced to stop after timeout";
  }
  return false;
}

class MockDeepStreamRunner final : public DeepStreamRunner {
 public:
  std::string runner_id() const override { return "mock"; }

  int run(
      const DeepStreamRunnerRequest& request,
      DeepStreamFourVisionGraph* graph,
      const DeepStreamExecutionPlan& /*plan*/) const override {
    if (graph == nullptr) {
      std::cout << bridge::encode_health_line({.state = "failed", .detail = "graph unavailable"}) << "\n";
      std::cout.flush();
      return 4;
    }
    std::cout << bridge::encode_health_line({.state = "ready", .detail = "mock detections streaming"}) << "\n";
    std::cout.flush();

    for (int i = 0; i < request.frames; ++i) {
      for (auto detection : graph->ingest_frame(request.source, i)) {
        std::cout << bridge::encode_detection_line(detection) << "\n";
      }
      std::cout.flush();
      std::this_thread::sleep_for(std::chrono::milliseconds(request.interval_ms));
    }

    std::cout << bridge::encode_health_line({.state = "stopping", .detail = "mock stream complete"}) << "\n";
    std::cout.flush();
    return 0;
  }
};

class RealDeepStreamRunner final : public DeepStreamRunner {
 public:
  std::string runner_id() const override { return "real"; }

  int run(
      const DeepStreamRunnerRequest& request,
      DeepStreamFourVisionGraph* /*graph*/,
      const DeepStreamExecutionPlan& plan) const override {
    if (!deepstream_execution_plan_valid(plan)) {
      std::cout << bridge::encode_health_line({.state = "failed", .detail = "real execution plan invalid"}) << "\n";
      std::cout.flush();
      return 2;
    }

    maybe_write_app_config(request.write_app_config, plan);
    const auto child = launch_deepstream_app(request.deepstream_app, request.write_app_config);
    if (!child.has_value()) {
      std::cout << bridge::encode_health_line({.state = "failed", .detail = "failed to launch deepstream-app"}) << "\n";
      std::cout.flush();
      return 3;
    }

    bool ready_emitted = false;
    std::uintmax_t offset = 0;
    if (!request.metadata_path.empty() && std::filesystem::exists(request.metadata_path)) {
      offset = std::filesystem::file_size(request.metadata_path);
    }

    const int sleep_ms = std::max(1, request.interval_ms);
    const int ready_deadline_ms = std::max(request.metadata_ready_timeout_ms, request.frames * request.interval_ms);
    const int max_polls = std::max(1, ready_deadline_ms / sleep_ms);
    ChildExitInfo last_exit{};
    for (int i = 0; i < max_polls; ++i) {
      for (const auto& line : read_metadata_lines(request.metadata_path, &offset)) {
        const auto envelope = bridge::parse_deepstream_line(line);
        if (!envelope.has_value()) {
          continue;
        }
        if (!ready_emitted && envelope->kind == bridge::DeepStreamEnvelope::Kind::Detection) {
          std::cout << bridge::encode_health_line(
                           {.state = "ready", .detail = "real runtime requested; four-branch execution plan active"})
                    << "\n";
          ready_emitted = true;
        }
        std::cout << line << "\n";
      }
      std::cout.flush();

      last_exit = poll_child_exit(child);
      if (last_exit.state != ChildExitState::Running) {
        break;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
    }

    if (!ready_emitted) {
      std::string detail = "real runtime produced no metadata before timeout";
      if (last_exit.state != ChildExitState::Running) {
        detail = describe_child_exit(last_exit) + " before metadata ready";
      }
      std::cout << bridge::encode_health_line({.state = "failed", .detail = detail}) << "\n";
      std::cout.flush();
      std::string shutdown_detail{};
      if (last_exit.state != ChildExitState::Running) {
        shutdown_detail = describe_child_exit(last_exit);
      } else {
        cleanup_deepstream_child(child, request.shutdown_timeout_ms, &shutdown_detail);
      }
      std::cout << bridge::encode_health_line({.state = "stopping", .detail = shutdown_detail}) << "\n";
      std::cout.flush();
      return 5;
    }

    std::string shutdown_detail{};
    const bool clean_shutdown = last_exit.state != ChildExitState::Running
                                    ? (shutdown_detail = describe_child_exit(last_exit),
                                       last_exit.state == ChildExitState::ExitedZero)
                                    : cleanup_deepstream_child(child, request.shutdown_timeout_ms, &shutdown_detail);
    std::cout << bridge::encode_health_line({.state = "stopping", .detail = shutdown_detail}) << "\n";
    std::cout.flush();
    return clean_shutdown ? 0 : 6;
  }
};

}  // namespace

std::unique_ptr<DeepStreamRunner> make_deepstream_runner(const std::string& mode) {
  if (mode == "real") {
    return std::make_unique<RealDeepStreamRunner>();
  }
  return std::make_unique<MockDeepStreamRunner>();
}

}  // namespace robot_life_cpp::perception
