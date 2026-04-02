#include "robot_life_cpp/bridge/deepstream_protocol.hpp"

#include <sstream>
#include <string_view>
#include <vector>

namespace robot_life_cpp::bridge {

namespace {
std::string escape(std::string_view input) {
  std::string out{};
  out.reserve(input.size());
  for (const auto ch : input) {
    switch (ch) {
      case '\\':
        out += "\\\\";
        break;
      case '|':
        out += "\\p";
        break;
      case ';':
        out += "\\s";
        break;
      case '=':
        out += "\\e";
        break;
      default:
        out.push_back(ch);
        break;
    }
  }
  return out;
}

std::string unescape(std::string_view input) {
  std::string out{};
  out.reserve(input.size());
  bool escaping = false;
  for (const auto ch : input) {
    if (!escaping) {
      if (ch == '\\') {
        escaping = true;
      } else {
        out.push_back(ch);
      }
      continue;
    }
    switch (ch) {
      case '\\':
        out.push_back('\\');
        break;
      case 'p':
        out.push_back('|');
        break;
      case 's':
        out.push_back(';');
        break;
      case 'e':
        out.push_back('=');
        break;
      default:
        out.push_back(ch);
        break;
    }
    escaping = false;
  }
  return out;
}

std::vector<std::string> split_fields(const std::string& line) {
  std::vector<std::string> fields{};
  std::string current{};
  bool escaping = false;
  for (const auto ch : line) {
    if (!escaping && ch == '|') {
      fields.push_back(current);
      current.clear();
      continue;
    }
    if (ch == '\\' && !escaping) {
      escaping = true;
      current.push_back(ch);
      continue;
    }
    escaping = false;
    current.push_back(ch);
  }
  fields.push_back(current);
  return fields;
}

common::Payload decode_payload(const std::string& encoded) {
  common::Payload payload{};
  std::string key{};
  std::string value{};
  bool reading_key = true;
  bool escaping = false;
  auto flush_pair = [&]() {
    if (!key.empty()) {
      payload[unescape(key)] = unescape(value);
    }
    key.clear();
    value.clear();
    reading_key = true;
  };

  for (const auto ch : encoded) {
    if (!escaping && ch == '\\') {
      escaping = true;
      (reading_key ? key : value).push_back(ch);
      continue;
    }
    if (!escaping && ch == '=') {
      reading_key = false;
      continue;
    }
    if (!escaping && ch == ';') {
      flush_pair();
      continue;
    }
    escaping = false;
    (reading_key ? key : value).push_back(ch);
  }
  flush_pair();
  return payload;
}

std::string encode_payload(const common::Payload& payload) {
  std::ostringstream oss;
  bool first = true;
  for (const auto& [key, value] : payload) {
    if (!first) {
      oss << ';';
    }
    first = false;
    oss << escape(key) << '=' << escape(value);
  }
  return oss.str();
}
}  // namespace

std::string encode_health_line(const DeepStreamHealthMessage& health) {
  std::ostringstream oss;
  oss << "HEALTH|" << escape(health.state) << "|" << escape(health.detail);
  return oss.str();
}

std::string encode_detection_line(const common::DetectionResult& detection) {
  std::ostringstream oss;
  oss << "DETECTION|" << escape(detection.trace_id) << "|" << escape(detection.source) << "|"
      << escape(detection.detector) << "|" << escape(detection.event_type) << "|"
      << detection.timestamp << "|" << detection.confidence << "|" << encode_payload(detection.payload);
  return oss.str();
}

std::optional<DeepStreamEnvelope> parse_deepstream_line(const std::string& line) {
  const auto fields = split_fields(line);
  if (fields.empty()) {
    return std::nullopt;
  }
  if (fields[0] == "HEALTH") {
    if (fields.size() < 3) {
      return std::nullopt;
    }
    DeepStreamEnvelope envelope{};
    envelope.kind = DeepStreamEnvelope::Kind::Health;
    envelope.health = DeepStreamHealthMessage{
        .state = unescape(fields[1]),
        .detail = unescape(fields[2]),
    };
    return envelope;
  }
  if (fields[0] == "DETECTION") {
    if (fields.size() < 8) {
      return std::nullopt;
    }
    common::DetectionResult detection{};
    detection.trace_id = unescape(fields[1]);
    detection.source = unescape(fields[2]);
    detection.detector = unescape(fields[3]);
    detection.event_type = unescape(fields[4]);
    detection.timestamp = std::stod(fields[5]);
    detection.confidence = std::stod(fields[6]);
    detection.payload = decode_payload(fields[7]);

    DeepStreamEnvelope envelope{};
    envelope.kind = DeepStreamEnvelope::Kind::Detection;
    envelope.detection = std::move(detection);
    return envelope;
  }
  return std::nullopt;
}

}  // namespace robot_life_cpp::bridge
