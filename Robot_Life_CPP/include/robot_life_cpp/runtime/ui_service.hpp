#pragma once

#include <atomic>
#include <cstddef>
#include <filesystem>
#include <string>
#include <thread>

namespace robot_life_cpp::runtime {

struct UiServiceConfig {
  std::string host{"127.0.0.1"};
  int port{8765};
  std::filesystem::path dashboard_html{std::filesystem::path("/tmp/robot_life_cpp_dashboard.html")};
  std::filesystem::path dashboard_json{std::filesystem::path("/tmp/robot_life_cpp_dashboard.json")};
  std::filesystem::path faces_db{std::filesystem::path("/tmp/robot_life_cpp_faces.tsv")};
  std::filesystem::path bindings_db{std::filesystem::path("/tmp/robot_life_cpp_bindings.tsv")};
  std::size_t max_header_bytes{16 * 1024};
  std::size_t max_request_body_bytes{4 * 1024 * 1024};
  std::size_t max_image_data_bytes{2 * 1024 * 1024};
  std::size_t max_face_records{256};
  std::size_t max_file_bytes{8 * 1024 * 1024};
  int socket_timeout_ms{1500};
  int accept_poll_ms{250};
};

class DebugUiService {
 public:
  explicit DebugUiService(UiServiceConfig config = {});
  ~DebugUiService();

  bool start(std::string* error = nullptr);
  void stop();
  bool running() const;
  std::string base_url() const;

 private:
  void run_loop();

  UiServiceConfig config_{};
  std::atomic<bool> running_{false};
  std::thread worker_{};
  int server_fd_{-1};
};

}  // namespace robot_life_cpp::runtime
