#include "robot_life_cpp/runtime/ui_service.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cctype>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include <system_error>

#include <sys/select.h>
#include <sys/time.h>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

namespace {

std::mutex g_store_mu{};

struct FaceRecord {
  std::string face_id;
  std::string name;
  std::string image_data;
  std::string created_at;
};

struct ParsedRequest {
  std::string method;
  std::string path;
  std::string version;
  std::size_t content_length{0};
  std::string body;
};

std::string trim_copy(std::string value) {
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(), [](unsigned char c) { return !std::isspace(c); }));
  value.erase(
      std::find_if(value.rbegin(), value.rend(), [](unsigned char c) { return !std::isspace(c); }).base(),
      value.end());
  return value;
}

std::string json_escape(const std::string& value) {
  std::ostringstream oss;
  for (const auto ch : value) {
    switch (ch) {
      case '\\':
        oss << "\\\\";
        break;
      case '"':
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

std::string url_encode(const std::string& value) {
  std::ostringstream oss;
  static constexpr char kHex[] = "0123456789ABCDEF";
  for (const auto ch : value) {
    const auto uch = static_cast<unsigned char>(ch);
    if ((uch >= 'a' && uch <= 'z') || (uch >= 'A' && uch <= 'Z') || (uch >= '0' && uch <= '9') ||
        uch == '-' || uch == '_' || uch == '.' || uch == '~') {
      oss << ch;
      continue;
    }
    oss << '%' << kHex[(uch >> 4) & 0x0F] << kHex[uch & 0x0F];
  }
  return oss.str();
}

std::string url_decode(const std::string& value) {
  std::string out;
  out.reserve(value.size());
  for (std::size_t i = 0; i < value.size(); ++i) {
    if (value[i] == '+') {
      out.push_back(' ');
      continue;
    }
    if (value[i] == '%' && i + 2 < value.size()) {
      const auto hex = value.substr(i + 1, 2);
      char* end = nullptr;
      const long code = std::strtol(hex.c_str(), &end, 16);
      if (end != nullptr && *end == '\0') {
        out.push_back(static_cast<char>(code));
        i += 2;
        continue;
      }
    }
    out.push_back(value[i]);
  }
  return out;
}

std::unordered_map<std::string, std::string> parse_form_urlencoded(const std::string& body) {
  std::unordered_map<std::string, std::string> out{};
  std::size_t start = 0;
  while (start <= body.size()) {
    const auto end = body.find('&', start);
    const auto pair = body.substr(start, end == std::string::npos ? std::string::npos : end - start);
    const auto eq = pair.find('=');
    if (eq != std::string::npos) {
      auto key = url_decode(pair.substr(0, eq));
      auto value = url_decode(pair.substr(eq + 1));
      if (!key.empty()) {
        out[key] = value;
      }
    }
    if (end == std::string::npos) {
      break;
    }
    start = end + 1;
  }
  return out;
}

bool file_size_within_limit(
    const std::filesystem::path& path,
    std::size_t max_bytes,
    std::size_t* file_size,
    std::string* error) {
  std::error_code ec{};
  const auto size = std::filesystem::exists(path, ec) ? std::filesystem::file_size(path, ec) : 0;
  if (ec) {
    if (error != nullptr) {
      *error = "failed to inspect file size: " + path.string();
    }
    return false;
  }
  if (file_size != nullptr) {
    *file_size = static_cast<std::size_t>(size);
  }
  if (size > static_cast<std::uintmax_t>(max_bytes)) {
    if (error != nullptr) {
      *error = "file exceeds size limit: " + path.string();
    }
    return false;
  }
  return true;
}

std::optional<std::string> read_text_file_with_limit(
    const std::filesystem::path& path,
    std::size_t max_bytes,
    std::string* error) {
  std::size_t size = 0;
  if (!file_size_within_limit(path, max_bytes, &size, error)) {
    return std::nullopt;
  }
  if (size == 0 && !std::filesystem::exists(path)) {
    if (error != nullptr) {
      *error = "missing file: " + path.string();
    }
    return std::nullopt;
  }

  std::ifstream in(path, std::ios::binary);
  if (!in.good()) {
    if (error != nullptr) {
      *error = "failed to open file: " + path.string();
    }
    return std::nullopt;
  }

  std::string out(size, '\0');
  if (size > 0) {
    in.read(out.data(), static_cast<std::streamsize>(out.size()));
    if (!in.good() && !in.eof()) {
      if (error != nullptr) {
        *error = "failed to read file: " + path.string();
      }
      return std::nullopt;
    }
  }
  if (error != nullptr) {
    error->clear();
  }
  return out;
}

bool write_text_file_atomic(
    const std::filesystem::path& path,
    const std::string& content,
    std::string* error) {
  const auto parent = path.parent_path();
  if (parent.empty()) {
    if (error != nullptr) {
      *error = "invalid output path: " + path.string();
    }
    return false;
  }
  std::error_code ec{};
  if (!std::filesystem::exists(parent, ec) && !std::filesystem::create_directories(parent, ec)) {
    if (error != nullptr) {
      *error = "failed to create output directory: " + parent.string();
    }
    return false;
  }

  auto temp_path = parent / (path.filename().string() + ".tmp." + common::new_id());
  {
    std::ofstream out(temp_path, std::ios::binary | std::ios::trunc);
    if (!out.good()) {
      if (error != nullptr) {
        *error = "failed to open temp file: " + temp_path.string();
      }
      return false;
    }
    out.write(content.data(), static_cast<std::streamsize>(content.size()));
    if (!out.good()) {
      if (error != nullptr) {
        *error = "failed to write temp file: " + temp_path.string();
      }
      std::filesystem::remove(temp_path, ec);
      return false;
    }
  }

  std::filesystem::rename(temp_path, path, ec);
  if (ec) {
    std::filesystem::remove(temp_path, ec);
    if (error != nullptr) {
      *error = "failed to rename temp file: " + path.string();
    }
    return false;
  }
  if (error != nullptr) {
    error->clear();
  }
  return true;
}

bool load_faces(
    const std::filesystem::path& path,
    std::size_t max_bytes,
    std::size_t max_records,
    std::vector<FaceRecord>* rows,
    std::string* error) {
  if (rows == nullptr) {
    if (error != nullptr) {
      *error = "face rows output is null";
    }
    return false;
  }
  rows->clear();

  std::size_t file_size = 0;
  if (!file_size_within_limit(path, max_bytes, &file_size, error)) {
    return false;
  }
  if (file_size == 0 && !std::filesystem::exists(path)) {
    if (error != nullptr) {
      error->clear();
    }
    return true;
  }

  std::ifstream in(path, std::ios::binary);
  if (!in.good()) {
    if (error != nullptr) {
      *error = "failed to open face db: " + path.string();
    }
    return false;
  }

  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) {
      continue;
    }
    std::vector<std::string> cols{};
    std::size_t start = 0;
    while (start <= line.size()) {
      const auto end = line.find('\t', start);
      cols.push_back(line.substr(start, end == std::string::npos ? std::string::npos : end - start));
      if (end == std::string::npos) {
        break;
      }
      start = end + 1;
    }
    if (cols.size() < 4) {
      continue;
    }
    FaceRecord row{
        .face_id = url_decode(cols[0]),
        .name = url_decode(cols[1]),
        .image_data = url_decode(cols[2]),
        .created_at = url_decode(cols[3]),
    };
    rows->push_back(std::move(row));
    if (rows->size() > max_records) {
      if (error != nullptr) {
        *error = "face db exceeds record limit: " + path.string();
      }
      rows->clear();
      return false;
    }
  }
  if (error != nullptr) {
    error->clear();
  }
  return true;
}

bool save_faces(
    const std::filesystem::path& path,
    const std::vector<FaceRecord>& rows,
    std::size_t max_bytes,
    std::string* error) {
  std::ostringstream out{};
  for (const auto& row : rows) {
    out << url_encode(row.face_id) << '\t' << url_encode(row.name) << '\t' << url_encode(row.image_data) << '\t'
        << url_encode(row.created_at) << '\n';
  }
  const auto content = out.str();
  if (content.size() > max_bytes) {
    if (error != nullptr) {
      *error = "face db exceeds file size limit: " + path.string();
    }
    return false;
  }
  return write_text_file_atomic(path, content, error);
}

bool load_bindings(
    const std::filesystem::path& path,
    std::size_t max_bytes,
    std::unordered_map<std::string, std::string>* out,
    std::string* error) {
  if (out == nullptr) {
    if (error != nullptr) {
      *error = "bindings output is null";
    }
    return false;
  }
  out->clear();

  std::size_t file_size = 0;
  if (!file_size_within_limit(path, max_bytes, &file_size, error)) {
    return false;
  }
  if (file_size == 0 && !std::filesystem::exists(path)) {
    if (error != nullptr) {
      error->clear();
    }
    return true;
  }

  std::ifstream in(path, std::ios::binary);
  if (!in.good()) {
    if (error != nullptr) {
      *error = "failed to open bindings db: " + path.string();
    }
    return false;
  }

  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) {
      continue;
    }
    const auto tab = line.find('\t');
    if (tab == std::string::npos) {
      continue;
    }
    auto target = url_decode(trim_copy(line.substr(0, tab)));
    auto face_id = url_decode(trim_copy(line.substr(tab + 1)));
    if (!target.empty() && !face_id.empty()) {
      (*out)[std::move(target)] = std::move(face_id);
    }
  }
  if (error != nullptr) {
    error->clear();
  }
  return true;
}

bool save_bindings(
    const std::filesystem::path& path,
    const std::unordered_map<std::string, std::string>& bindings,
    std::size_t max_bytes,
    std::string* error) {
  std::ostringstream out{};
  for (const auto& [target, face_id] : bindings) {
    out << url_encode(target) << '\t' << url_encode(face_id) << '\n';
  }
  const auto content = out.str();
  if (content.size() > max_bytes) {
    if (error != nullptr) {
      *error = "bindings db exceeds file size limit: " + path.string();
    }
    return false;
  }
  return write_text_file_atomic(path, content, error);
}

std::optional<std::string> parse_json_string_at(const std::string& json, std::size_t* pos) {
  if (pos == nullptr || *pos >= json.size() || json[*pos] != '"') {
    return std::nullopt;
  }
  ++(*pos);
  std::string out;
  while (*pos < json.size()) {
    const auto ch = json[*pos];
    if (ch == '"') {
      ++(*pos);
      return out;
    }
    if (ch != '\\') {
      out.push_back(ch);
      ++(*pos);
      continue;
    }
    ++(*pos);
    if (*pos >= json.size()) {
      return std::nullopt;
    }
    const auto esc = json[*pos];
    switch (esc) {
      case '"':
      case '\\':
      case '/':
        out.push_back(esc);
        break;
      case 'b':
        out.push_back('\b');
        break;
      case 'f':
        out.push_back('\f');
        break;
      case 'n':
        out.push_back('\n');
        break;
      case 'r':
        out.push_back('\r');
        break;
      case 't':
        out.push_back('\t');
        break;
      case 'u': {
        if (*pos + 4 >= json.size()) {
          return std::nullopt;
        }
        unsigned int codepoint = 0;
        for (std::size_t i = 1; i <= 4; ++i) {
          const auto hex = json[*pos + i];
          codepoint <<= 4U;
          if (hex >= '0' && hex <= '9') {
            codepoint |= static_cast<unsigned int>(hex - '0');
          } else if (hex >= 'a' && hex <= 'f') {
            codepoint |= static_cast<unsigned int>(hex - 'a' + 10);
          } else if (hex >= 'A' && hex <= 'F') {
            codepoint |= static_cast<unsigned int>(hex - 'A' + 10);
          } else {
            return std::nullopt;
          }
        }
        if (codepoint <= 0x7FU) {
          out.push_back(static_cast<char>(codepoint));
        } else if (codepoint <= 0x7FFU) {
          out.push_back(static_cast<char>(0xC0U | ((codepoint >> 6U) & 0x1FU)));
          out.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
        } else {
          if (codepoint >= 0xD800U && codepoint <= 0xDFFFU) {
            return std::nullopt;
          }
          out.push_back(static_cast<char>(0xE0U | ((codepoint >> 12U) & 0x0FU)));
          out.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
          out.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
        }
        *pos += 4;
        break;
      }
      default:
        return std::nullopt;
    }
    ++(*pos);
  }
  return std::nullopt;
}

std::optional<std::string> parse_json_string_field(const std::string& json, const std::string& field_name) {
  const std::string needle = "\"" + field_name + "\"";
  const auto field_pos = json.find(needle);
  if (field_pos == std::string::npos) {
    return std::nullopt;
  }
  auto pos = field_pos + needle.size();
  while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) {
    ++pos;
  }
  if (pos >= json.size() || json[pos] != ':') {
    return std::nullopt;
  }
  ++pos;
  while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) {
    ++pos;
  }
  if (pos >= json.size()) {
    return std::nullopt;
  }
  if (json.compare(pos, 4, "null") == 0) {
    return std::nullopt;
  }
  auto parsed = parse_json_string_at(json, &pos);
  if (!parsed.has_value()) {
    return std::nullopt;
  }
  return parsed;
}

std::optional<std::string> parse_active_target_id(const std::string& state_json) {
  return parse_json_string_field(state_json, "active_target_id");
}

std::optional<std::string> read_state_json(
    const std::filesystem::path& path,
    std::size_t max_bytes,
    std::string* error) {
  return read_text_file_with_limit(path, max_bytes, error);
}

std::string now_iso_string() {
  return std::to_string(static_cast<long long>(common::now_wall()));
}

std::string http_status_text(int code) {
  switch (code) {
    case 408:
      return "Request Timeout";
    case 200:
      return "OK";
    case 201:
      return "Created";
    case 400:
      return "Bad Request";
    case 413:
      return "Payload Too Large";
    case 404:
      return "Not Found";
    case 405:
      return "Method Not Allowed";
    case 500:
      return "Internal Server Error";
    default:
      return "OK";
  }
}

bool send_all(int fd, const std::string& data) {
  std::size_t offset = 0;
  while (offset < data.size()) {
    const auto n = send(fd, data.data() + offset, data.size() - offset, 0);
    if (n < 0) {
      if (errno == EINTR) {
        continue;
      }
      return false;
    }
    if (n == 0) {
      return false;
    }
    offset += static_cast<std::size_t>(n);
  }
  return true;
}

bool send_http_response(int fd, int code, const std::string& content_type, const std::string& body) {
  std::ostringstream oss;
  oss << "HTTP/1.1 " << code << " " << http_status_text(code) << "\r\n";
  oss << "Content-Type: " << content_type << "\r\n";
  oss << "Content-Length: " << body.size() << "\r\n";
  oss << "Connection: close\r\n";
  oss << "Cache-Control: no-store\r\n";
  oss << "X-Content-Type-Options: nosniff\r\n";
  oss << "\r\n";
  const auto header = oss.str();
  if (!send_all(fd, header)) {
    return false;
  }
  if (!body.empty() && !send_all(fd, body)) {
    return false;
  }
  return true;
}

bool send_json_error(int fd, int code, const std::string& message) {
  const auto body = std::string{"{\"ok\":false,\"error\":\""} + json_escape(message) + "\"}";
  return send_http_response(fd, code, "application/json; charset=utf-8", body);
}

std::string build_faces_json(const std::vector<FaceRecord>& faces) {
  std::ostringstream oss;
  oss << "{\"ok\":true,\"faces\":[";
  for (std::size_t i = 0; i < faces.size(); ++i) {
    if (i > 0) {
      oss << ',';
    }
    const auto& f = faces[i];
    oss << "{\"face_id\":\"" << json_escape(f.face_id) << "\","
        << "\"name\":\"" << json_escape(f.name) << "\","
        << "\"image_data\":\"" << json_escape(f.image_data) << "\","
        << "\"created_at\":\"" << json_escape(f.created_at) << "\"}";
  }
  oss << "]}";
  return oss.str();
}

std::string build_bindings_json(const std::unordered_map<std::string, std::string>& bindings) {
  std::ostringstream oss;
  oss << "{\"ok\":true,\"bindings\":{";
  bool first = true;
  for (const auto& [target, face_id] : bindings) {
    if (!first) {
      oss << ',';
    }
    first = false;
    oss << "\"" << json_escape(target) << "\":\"" << json_escape(face_id) << "\"";
  }
  oss << "}}";
  return oss.str();
}

void lower_case_in_place(std::string* value) {
  if (value == nullptr) {
    return;
  }
  std::transform(value->begin(), value->end(), value->begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
}

bool set_client_timeouts(int fd, int timeout_ms) {
  const timeval tv{
      .tv_sec = timeout_ms / 1000,
      .tv_usec = (timeout_ms % 1000) * 1000,
  };
  if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) < 0) {
    return false;
  }
  if (setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv)) < 0) {
    return false;
  }
  return true;
}

bool wait_for_accept(int fd, int timeout_ms) {
  fd_set readfds;
  FD_ZERO(&readfds);
  FD_SET(fd, &readfds);
  timeval tv{
      .tv_sec = timeout_ms / 1000,
      .tv_usec = (timeout_ms % 1000) * 1000,
  };
  while (true) {
    const auto ready = select(fd + 1, &readfds, nullptr, nullptr, &tv);
    if (ready > 0) {
      return FD_ISSET(fd, &readfds);
    }
    if (ready == 0) {
      return false;
    }
    if (errno == EINTR) {
      FD_ZERO(&readfds);
      FD_SET(fd, &readfds);
      tv.tv_sec = timeout_ms / 1000;
      tv.tv_usec = (timeout_ms % 1000) * 1000;
      continue;
    }
    return false;
  }
}

bool parse_http_request(int fd, const UiServiceConfig& config, ParsedRequest* out, std::string* error) {
  if (out == nullptr) {
    if (error != nullptr) {
      *error = "request output is null";
    }
    return false;
  }
  out->body.clear();
  out->method.clear();
  out->path.clear();
  out->version.clear();
  out->content_length = 0;

  if (!set_client_timeouts(fd, config.socket_timeout_ms)) {
    if (error != nullptr) {
      *error = std::string{"failed to configure socket timeout: "} + std::strerror(errno);
    }
    return false;
  }

  std::string request{};
  request.reserve(4096);
  std::array<char, 4096> buf{};
  while (request.find("\r\n\r\n") == std::string::npos) {
    if (request.size() > config.max_header_bytes) {
      if (error != nullptr) {
        *error = "request header exceeds limit";
      }
      return false;
    }
    const auto n = recv(fd, buf.data(), buf.size(), 0);
    if (n == 0) {
      if (error != nullptr) {
        *error = "client closed connection";
      }
      return false;
    }
    if (n < 0) {
      if (errno == EINTR) {
        continue;
      }
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        if (error != nullptr) {
          *error = "request timeout";
        }
        return false;
      }
      if (error != nullptr) {
        *error = std::string{"request read failed: "} + std::strerror(errno);
      }
      return false;
    }
    request.append(buf.data(), static_cast<std::size_t>(n));
    if (request.size() > config.max_header_bytes) {
      if (error != nullptr) {
        *error = "request header exceeds limit";
      }
      return false;
    }
  }

  const auto header_end = request.find("\r\n\r\n");
  if (header_end == std::string::npos) {
    if (error != nullptr) {
      *error = "malformed request headers";
    }
    return false;
  }
  const auto headers = request.substr(0, header_end);
  out->body = request.substr(header_end + 4);

  std::istringstream hss(headers);
  std::string first_line;
  std::getline(hss, first_line);
  if (!first_line.empty() && first_line.back() == '\r') {
    first_line.pop_back();
  }

  std::istringstream fl(first_line);
  fl >> out->method >> out->path >> out->version;
  if (out->method.empty() || out->path.empty() || out->version.empty()) {
    if (error != nullptr) {
      *error = "malformed request line";
    }
    return false;
  }

  std::size_t content_length = 0;
  std::string line;
  while (std::getline(hss, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    const auto colon = line.find(':');
    if (colon == std::string::npos) {
      continue;
    }
    auto key = trim_copy(line.substr(0, colon));
    auto value = trim_copy(line.substr(colon + 1));
    lower_case_in_place(&key);
    if (key == "content-length") {
      try {
        content_length = static_cast<std::size_t>(std::stoull(value));
      } catch (...) {
        if (error != nullptr) {
          *error = "invalid content-length";
        }
        return false;
      }
    }
  }

  if (out->method == "POST" && content_length == 0) {
    if (error != nullptr) {
      *error = "content-length is required";
    }
    return false;
  }
  if (content_length > config.max_request_body_bytes) {
    if (error != nullptr) {
      *error = "request body exceeds limit";
    }
    return false;
  }

  if (out->body.size() > content_length) {
    out->body.resize(content_length);
  }
  while (out->body.size() < content_length) {
    const auto n = recv(fd, buf.data(), buf.size(), 0);
    if (n == 0) {
      if (error != nullptr) {
        *error = "client closed connection before request body completed";
      }
      return false;
    }
    if (n < 0) {
      if (errno == EINTR) {
        continue;
      }
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        if (error != nullptr) {
          *error = "request timeout";
        }
        return false;
      }
      if (error != nullptr) {
        *error = std::string{"request body read failed: "} + std::strerror(errno);
      }
      return false;
    }
    const auto remaining = content_length - out->body.size();
    const auto take = std::min<std::size_t>(remaining, static_cast<std::size_t>(n));
    out->body.append(buf.data(), take);
    if (out->body.size() > config.max_request_body_bytes) {
      if (error != nullptr) {
        *error = "request body exceeds limit";
      }
      return false;
    }
  }

  out->content_length = content_length;
  if (error != nullptr) {
    error->clear();
  }
  return true;
}

int status_code_for_error(const std::string& error) {
  if (error.find("timeout") != std::string::npos) {
    return 408;
  }
  if (error.find("exceeds limit") != std::string::npos ||
      error.find("too large") != std::string::npos) {
    return 413;
  }
  if (error.find("method") != std::string::npos) {
    return 405;
  }
  return 400;
}

bool handle_request(int client_fd, const UiServiceConfig& config) {
  ParsedRequest request{};
  std::string error{};
  if (!parse_http_request(client_fd, config, &request, &error)) {
    const auto status = status_code_for_error(error);
    (void)send_json_error(client_fd, status, error);
    return false;
  }

  const auto query_pos = request.path.find('?');
  if (query_pos != std::string::npos) {
    request.path = request.path.substr(0, query_pos);
  }

  if (request.method == "GET" && request.path == "/") {
    std::string file_error{};
    auto html = read_text_file_with_limit(config.dashboard_html, config.max_file_bytes, &file_error);
    if (!html.has_value()) {
      html = std::string{
          "<!doctype html><html><body style='font-family:sans-serif'><h2>Dashboard not ready</h2>"
          "<p>Run <code>ui-demo</code> and refresh.</p></body></html>"};
    }
    (void)send_http_response(client_fd, 200, "text/html; charset=utf-8", *html);
    return true;
  }

  if (request.method == "GET" && request.path == "/api/state") {
    std::string state_error{};
    auto state = read_state_json(config.dashboard_json, config.max_file_bytes, &state_error);
    if (!state.has_value()) {
      (void)send_json_error(client_fd, 500, state_error);
      return false;
    }
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", *state);
    return true;
  }

  if (request.method == "GET" && request.path == "/api/faces") {
    std::vector<FaceRecord> faces{};
    std::string faces_error{};
    std::lock_guard<std::mutex> lock(g_store_mu);
    if (!load_faces(config.faces_db, config.max_file_bytes, config.max_face_records, &faces, &faces_error)) {
      (void)send_json_error(client_fd, 500, faces_error);
      return false;
    }
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", build_faces_json(faces));
    return true;
  }

  if (request.method == "POST" && request.path == "/api/faces") {
    const auto form = parse_form_urlencoded(request.body);
    const auto name_it = form.find("name");
    const auto image_it = form.find("image_data");
    if (name_it == form.end() || name_it->second.empty() || image_it == form.end() || image_it->second.empty()) {
      (void)send_json_error(client_fd, 400, "name and image_data are required");
      return false;
    }
    if (image_it->second.size() > config.max_image_data_bytes) {
      (void)send_json_error(client_fd, 413, "image_data exceeds limit");
      return false;
    }

    std::lock_guard<std::mutex> lock(g_store_mu);
    std::vector<FaceRecord> faces{};
    std::string faces_error{};
    if (!load_faces(config.faces_db, config.max_file_bytes, config.max_face_records, &faces, &faces_error)) {
      (void)send_json_error(client_fd, 500, faces_error);
      return false;
    }
    if (faces.size() >= config.max_face_records) {
      (void)send_json_error(client_fd, 413, "face library is full");
      return false;
    }

    FaceRecord record{};
    record.face_id = "face_" + common::new_id();
    record.name = name_it->second;
    record.image_data = image_it->second;
    record.created_at = now_iso_string();
    faces.push_back(record);

    if (!save_faces(config.faces_db, faces, config.max_file_bytes, &faces_error)) {
      (void)send_json_error(client_fd, 500, faces_error);
      return false;
    }

    std::ostringstream oss;
    oss << "{\"ok\":true,\"face\":{\"face_id\":\"" << json_escape(record.face_id) << "\","
        << "\"name\":\"" << json_escape(record.name) << "\"}}";
    (void)send_http_response(client_fd, 201, "application/json; charset=utf-8", oss.str());
    return true;
  }

  if (request.method == "DELETE" && request.path.rfind("/api/faces/", 0) == 0) {
    const auto face_id = url_decode(request.path.substr(std::string{"/api/faces/"}.size()));
    std::lock_guard<std::mutex> lock(g_store_mu);
    std::vector<FaceRecord> faces{};
    std::string faces_error{};
    if (!load_faces(config.faces_db, config.max_file_bytes, config.max_face_records, &faces, &faces_error)) {
      (void)send_json_error(client_fd, 500, faces_error);
      return false;
    }
    const auto before = faces.size();
    faces.erase(
        std::remove_if(faces.begin(), faces.end(), [&](const FaceRecord& row) { return row.face_id == face_id; }),
        faces.end());
    std::unordered_map<std::string, std::string> bindings{};
    std::string bindings_error{};
    if (!load_bindings(config.bindings_db, config.max_file_bytes, &bindings, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    for (auto it = bindings.begin(); it != bindings.end();) {
      if (it->second == face_id) {
        it = bindings.erase(it);
      } else {
        ++it;
      }
    }
    if (!save_faces(config.faces_db, faces, config.max_file_bytes, &faces_error) ||
        !save_bindings(config.bindings_db, bindings, config.max_file_bytes, &bindings_error)) {
      (void)send_json_error(client_fd, 500, !faces_error.empty() ? faces_error : bindings_error);
      return false;
    }
    std::ostringstream oss;
    oss << "{\"ok\":true,\"deleted\":" << (before != faces.size() ? "true" : "false") << "}";
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", oss.str());
    return true;
  }

  if (request.method == "GET" && request.path == "/api/bindings") {
    std::unordered_map<std::string, std::string> bindings{};
    std::string bindings_error{};
    std::lock_guard<std::mutex> lock(g_store_mu);
    if (!load_bindings(config.bindings_db, config.max_file_bytes, &bindings, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", build_bindings_json(bindings));
    return true;
  }

  if (request.method == "POST" && request.path == "/api/bindings") {
    const auto form = parse_form_urlencoded(request.body);
    const auto target_it = form.find("target_id");
    const auto face_it = form.find("face_id");
    if (target_it == form.end() || target_it->second.empty() || face_it == form.end() || face_it->second.empty()) {
      (void)send_json_error(client_fd, 400, "target_id and face_id are required");
      return false;
    }

    std::lock_guard<std::mutex> lock(g_store_mu);
    std::vector<FaceRecord> faces{};
    std::unordered_map<std::string, std::string> bindings{};
    std::string faces_error{};
    std::string bindings_error{};
    if (!load_faces(config.faces_db, config.max_file_bytes, config.max_face_records, &faces, &faces_error)) {
      (void)send_json_error(client_fd, 500, faces_error);
      return false;
    }
    const auto has_face = std::any_of(faces.begin(), faces.end(), [&](const FaceRecord& row) {
      return row.face_id == face_it->second;
    });
    if (!has_face) {
      (void)send_json_error(client_fd, 404, "face_id not found");
      return false;
    }
    if (!load_bindings(config.bindings_db, config.max_file_bytes, &bindings, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    bindings[target_it->second] = face_it->second;
    if (!save_bindings(config.bindings_db, bindings, config.max_file_bytes, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", "{\"ok\":true}");
    return true;
  }

  if (request.method == "DELETE" && request.path.rfind("/api/bindings/", 0) == 0) {
    const auto target_id = url_decode(request.path.substr(std::string{"/api/bindings/"}.size()));
    std::lock_guard<std::mutex> lock(g_store_mu);
    std::unordered_map<std::string, std::string> bindings{};
    std::string bindings_error{};
    if (!load_bindings(config.bindings_db, config.max_file_bytes, &bindings, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    const auto erased = bindings.erase(target_id);
    if (!save_bindings(config.bindings_db, bindings, config.max_file_bytes, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    std::ostringstream oss;
    oss << "{\"ok\":true,\"deleted\":" << (erased > 0 ? "true" : "false") << "}";
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", oss.str());
    return true;
  }

  if (request.method == "GET" && request.path == "/api/recognition") {
    std::string state_error{};
    std::lock_guard<std::mutex> lock(g_store_mu);
    auto state = read_state_json(config.dashboard_json, config.max_file_bytes, &state_error);
    if (!state.has_value()) {
      (void)send_json_error(client_fd, 500, state_error);
      return false;
    }
    const auto active_target = parse_active_target_id(*state);
    std::unordered_map<std::string, std::string> bindings{};
    std::vector<FaceRecord> faces{};
    std::string bindings_error{};
    std::string faces_error{};
    if (!load_bindings(config.bindings_db, config.max_file_bytes, &bindings, &bindings_error)) {
      (void)send_json_error(client_fd, 500, bindings_error);
      return false;
    }
    if (!load_faces(config.faces_db, config.max_file_bytes, config.max_face_records, &faces, &faces_error)) {
      (void)send_json_error(client_fd, 500, faces_error);
      return false;
    }

    std::string face_id;
    std::string person_name;
    if (active_target.has_value()) {
      if (const auto it = bindings.find(*active_target); it != bindings.end()) {
        face_id = it->second;
        if (const auto fit = std::find_if(faces.begin(), faces.end(), [&](const FaceRecord& row) {
              return row.face_id == face_id;
            });
            fit != faces.end()) {
          person_name = fit->name;
        }
      }
    }

    std::ostringstream oss;
    oss << "{\"ok\":true,\"active_target_id\":";
    if (active_target.has_value()) {
      oss << "\"" << json_escape(*active_target) << "\"";
    } else {
      oss << "null";
    }
    oss << ",\"recognized\":" << (!person_name.empty() ? "true" : "false")
        << ",\"face_id\":";
    if (!face_id.empty()) {
      oss << "\"" << json_escape(face_id) << "\"";
    } else {
      oss << "null";
    }
    oss << ",\"person_name\":";
    if (!person_name.empty()) {
      oss << "\"" << json_escape(person_name) << "\"";
    } else {
      oss << "null";
    }
    oss << "}";
    (void)send_http_response(client_fd, 200, "application/json; charset=utf-8", oss.str());
    return true;
  }

  const auto method_supported = request.method == "GET" || request.method == "POST" || request.method == "DELETE";
  (void)send_json_error(client_fd, method_supported ? 404 : 405, "unsupported endpoint");
  return false;
}

}  // namespace

DebugUiService::DebugUiService(UiServiceConfig config) : config_(std::move(config)) {}

DebugUiService::~DebugUiService() { stop(); }

bool DebugUiService::start(std::string* error) {
  if (running_.load()) {
    return true;
  }

  std::signal(SIGPIPE, SIG_IGN);

  server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd_ < 0) {
    if (error != nullptr) {
      *error = std::string{"ui service socket failed: "} + std::strerror(errno);
    }
    return false;
  }

  const int enable = 1;
  (void)setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof(enable));

  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(static_cast<uint16_t>(config_.port));
  addr.sin_addr.s_addr = inet_addr(config_.host.c_str());
  if (bind(server_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
    if (error != nullptr) {
      *error = std::string{"ui service bind failed: "} + std::strerror(errno);
    }
    close(server_fd_);
    server_fd_ = -1;
    return false;
  }

  if (listen(server_fd_, 16) < 0) {
    if (error != nullptr) {
      *error = std::string{"ui service listen failed: "} + std::strerror(errno);
    }
    close(server_fd_);
    server_fd_ = -1;
    return false;
  }

  running_.store(true);
  worker_ = std::thread([this]() { run_loop(); });
  return true;
}

void DebugUiService::stop() {
  if (!running_.exchange(false)) {
    return;
  }
  if (server_fd_ >= 0) {
    shutdown(server_fd_, SHUT_RDWR);
    close(server_fd_);
    server_fd_ = -1;
  }
  if (worker_.joinable()) {
    worker_.join();
  }
}

bool DebugUiService::running() const { return running_.load(); }

std::string DebugUiService::base_url() const {
  return "http://" + config_.host + ":" + std::to_string(config_.port);
}

void DebugUiService::run_loop() {
  while (running_.load()) {
    if (!wait_for_accept(server_fd_, config_.accept_poll_ms)) {
      if (!running_.load()) {
        break;
      }
      continue;
    }

    sockaddr_in client_addr{};
    socklen_t client_len = sizeof(client_addr);
    const int client_fd = accept(server_fd_, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
    if (client_fd < 0) {
      if (running_.load()) {
        continue;
      }
      break;
    }

    (void)handle_request(client_fd, config_);
    close(client_fd);
  }
}

}  // namespace robot_life_cpp::runtime
