#include "robot_life_cpp/root/cli.hpp"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string_view>
#include <vector>

#include "robot_life_cpp/root/cli_shared.hpp"
#include "robot_life_cpp/migration/module_catalog.hpp"
#include "robot_life_cpp/runtime/cuda_probe.hpp"
#include "robot_life_cpp/runtime/profile_registry.hpp"

namespace robot_life_cpp::root {

namespace {
struct DoctorCheck {
  bool ok{false};
  std::string name;
  std::string detail;
};

void print_check(const DoctorCheck& check) {
  std::cout << "  [" << (check.ok ? "ok" : "fail") << "] " << check.name;
  if (!check.detail.empty()) {
    std::cout << ": " << check.detail;
  }
  std::cout << "\n";
}

std::string host_platform() {
#if defined(__APPLE__)
  return "macos";
#elif defined(__linux__)
  return "linux";
#elif defined(_WIN32)
  return "windows";
#else
  return "unknown";
#endif
}

DoctorCheck check_file_exists(std::string name, const std::filesystem::path& path) {
  const bool exists = std::filesystem::exists(path);
  return {
      .ok = exists,
      .name = std::move(name),
      .detail = exists ? path.string() : ("missing: " + path.string()),
  };
}

DoctorCheck check_directory_exists(std::string name, const std::filesystem::path& path) {
  const bool exists = std::filesystem::exists(path) && std::filesystem::is_directory(path);
  return {
      .ok = exists,
      .name = std::move(name),
      .detail = exists ? path.string() : ("missing directory: " + path.string()),
  };
}

std::filesystem::path find_on_path(const std::string_view name) {
  const char* raw = std::getenv("PATH");
  if (raw == nullptr || *raw == '\0') {
    return {};
  }
  std::stringstream stream{raw};
  std::string entry{};
  while (std::getline(stream, entry, ':')) {
    if (entry.empty()) {
      continue;
    }
    const auto candidate = std::filesystem::path{entry} / name;
    if (std::filesystem::exists(candidate) && !std::filesystem::is_directory(candidate)) {
      return candidate;
    }
  }
  return {};
}
}  // namespace

int doctor(std::span<const std::string> /*args*/) {
  std::vector<DoctorCheck> checks{};
  checks.reserve(12);

  std::cout << "Robot Life C++ Doctor\n";
  std::cout << "  version: " << version() << "\n";
  std::cout << "  platform: " << host_platform() << "\n";
  std::cout << "  module_migration: "
            << migration::implemented_module_count() << "/"
            << migration::total_module_count() << "\n";

  checks.push_back(check_file_exists("config", default_config_path()));
  checks.push_back(check_file_exists("detector_config", default_detector_config_path()));
  checks.push_back(check_file_exists("slow_scene_config", default_slow_scene_config_path()));
  checks.push_back(check_file_exists("stabilizer_config", default_stabilizer_config_path()));
  checks.push_back(check_file_exists("runtime_tuning_config", default_runtime_tuning_path()));
  checks.push_back(check_file_exists("deepstream_graph_config", "configs/deepstream_4vision.yaml"));
  checks.push_back(check_file_exists("profile_catalog", "configs/profile_catalog.yaml"));
  checks.push_back(check_directory_exists("model_store", "models"));

  runtime::ProfileRegistry profile_registry{"configs/profile_catalog.yaml"};
  const bool profiles_loaded = profile_registry.load();
  checks.push_back({
      .ok = profiles_loaded,
      .name = "profile_registry",
      .detail = profiles_loaded ? ("default=" + profile_registry.default_profile())
                                : profile_registry.error_message(),
  });
  if (profiles_loaded) {
    checks.push_back({
        .ok = profile_registry.has_profile("mac_debug_native"),
        .name = "profile:mac_debug_native",
        .detail = "native development profile",
    });
    checks.push_back({
        .ok = profile_registry.has_profile("linux_deepstream_4vision"),
        .name = "profile:linux_deepstream_4vision",
        .detail = "DeepStream production profile",
    });
    checks.push_back({
        .ok = profile_registry.has_profile("linux_cpu_fallback_safe"),
        .name = "profile:linux_cpu_fallback_safe",
        .detail = "safe CPU fallback profile",
    });
  }

  const auto cuda = runtime::probe_cuda_runtime();
  checks.push_back({
      .ok = true,
      .name = "cuda_runtime",
      .detail = cuda.available ? ("available devices=" + std::to_string(cuda.device_count))
                               : cuda.message,
  });

  const char* deepstream_dir = std::getenv("DEEPSTREAM_DIR");
  const bool deepstream_env_present = deepstream_dir != nullptr && *deepstream_dir != '\0';
  const bool deepstream_default_present =
      std::filesystem::exists("/opt/nvidia/deepstream/deepstream");
  const auto deepstream_app = []() -> std::filesystem::path {
    const char* explicit_app = std::getenv("DEEPSTREAM_APP");
    if (explicit_app != nullptr && *explicit_app != '\0') {
      return explicit_app;
    }
    const auto on_path = find_on_path("deepstream-app");
    if (!on_path.empty()) {
      return on_path;
    }
    return "/opt/nvidia/deepstream/deepstream/bin/deepstream-app";
  }();
  checks.push_back({
      .ok = host_platform() != "linux" || deepstream_env_present || deepstream_default_present,
      .name = "deepstream_runtime_hint",
      .detail = deepstream_env_present ? deepstream_dir
                                       : (deepstream_default_present
                                              ? "/opt/nvidia/deepstream/deepstream"
                                              : "set DEEPSTREAM_DIR or install under /opt/nvidia/deepstream/deepstream"),
  });
  checks.push_back({
      .ok = host_platform() != "linux" || std::filesystem::exists(deepstream_app),
      .name = "deepstream_app",
      .detail = deepstream_app.string(),
  });
  const auto metadata_path = []() -> std::filesystem::path {
    const char* configured = std::getenv("ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH");
    if (configured != nullptr && *configured != '\0') {
      return configured;
    }
    return "/tmp/robot_life_cpp_deepstream_metadata.ndjson";
  }();
  checks.push_back({
      .ok = host_platform() != "linux" ||
            (!metadata_path.empty() && !metadata_path.parent_path().empty() &&
             std::filesystem::exists(metadata_path.parent_path())),
      .name = "deepstream_metadata_bridge",
      .detail = metadata_path.string(),
  });

  bool all_ok = true;
  for (const auto& check : checks) {
    print_check(check);
    all_ok = all_ok && check.ok;
  }

  if (host_platform() != "linux") {
    std::cout << "  [note] DeepStream production backend targets Linux + NVIDIA dGPU. "
                 "This host can still use the native/mac development profile.\n";
  }
  return all_ok ? 0 : 1;
}

int detector_status(std::span<const std::string> /*args*/) {
  const auto cuda = runtime::probe_cuda_runtime();
  std::cout << "Detector Status\n";
  std::cout << "  cuda_available: " << (cuda.available ? "true" : "false") << "\n";
  std::cout << "  cuda_devices: " << cuda.device_count << "\n";
  std::cout << "  message: " << cuda.message << "\n";
  return 0;
}

}  // namespace robot_life_cpp::root
