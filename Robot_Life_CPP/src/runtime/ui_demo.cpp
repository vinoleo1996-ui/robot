#include "robot_life_cpp/runtime/ui_demo.hpp"

#include <fstream>
#include <sstream>

#include <sys/resource.h>

namespace robot_life_cpp::runtime {

namespace {
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

std::string html_escape(const std::string& value) {
  std::ostringstream oss;
  for (const auto ch : value) {
    switch (ch) {
      case '&':
        oss << "&amp;";
        break;
      case '<':
        oss << "&lt;";
        break;
      case '>':
        oss << "&gt;";
        break;
      case '"':
        oss << "&quot;";
        break;
      default:
        oss << ch;
        break;
    }
  }
  return oss.str();
}

double process_memory_mb() {
  struct rusage usage {};
  if (getrusage(RUSAGE_SELF, &usage) != 0) {
    return 0.0;
  }
#if defined(__APPLE__)
  return static_cast<double>(usage.ru_maxrss) / (1024.0 * 1024.0);
#else
  return static_cast<double>(usage.ru_maxrss) / 1024.0;
#endif
}

std::string format_detection_preview(const common::DetectionResult& detection) {
  std::ostringstream out;
  out << detection.detector << " -> " << detection.event_type;
  const auto class_it = detection.payload.find("class_name");
  if (class_it != detection.payload.end()) {
    out << " (" << class_it->second << ")";
  }
  return out.str();
}

std::string health_phase_name(RuntimePhase phase) {
  switch (phase) {
    case RuntimePhase::Starting:
      return "starting";
    case RuntimePhase::Warming:
      return "warming";
    case RuntimePhase::Ready:
      return "ready";
    case RuntimePhase::Degraded:
      return "degraded";
    case RuntimePhase::Failed:
      return "failed";
    case RuntimePhase::Stopping:
      return "stopping";
    case RuntimePhase::Stopped:
      return "stopped";
  }
  return "unknown";
}
}  // namespace

std::string render_debug_dashboard_json(const DebugDashboardData& data) {
  std::ostringstream oss;
  oss << "{";
  oss << "\"platform\":\"" << json_escape(data.platform) << "\",";
  oss << "\"gpu_summary\":\"" << json_escape(data.gpu_summary) << "\",";
  oss << "\"process_memory_mb\":" << data.process_memory_mb << ",";
  oss << "\"load_shed\":{\"pressure\":\"" << json_escape(to_string(data.load_shed.pressure)) << "\","
      << "\"reason\":\"" << json_escape(data.load_shed.reason) << "\","
      << "\"max_events_per_batch\":" << data.load_shed.max_events_per_batch << ","
      << "\"preview_enabled\":" << (data.load_shed.preview_enabled ? "true" : "false") << ","
      << "\"preview_every_ticks\":" << data.load_shed.preview_every_ticks << ","
      << "\"telemetry_every_ticks\":" << data.load_shed.telemetry_every_ticks << "},";
  oss << "\"runtime\":{\"pending_events\":" << data.runtime.pending_events
      << ",\"stable_events_last_tick\":" << data.runtime.stable_events_last_tick
      << ",\"scene_candidates_last_tick\":" << data.runtime.scene_candidates_last_tick << "},";
  oss << "\"backend\":{\"backend_id\":\"" << json_escape(data.backend.backend_id) << "\","
      << "\"running\":" << (data.backend.running ? "true" : "false") << ","
      << "\"delivered_batches\":" << data.backend.delivered_batches << ","
      << "\"delivered_detections\":" << data.backend.delivered_detections << "},";
  const auto phase_name = health_phase_name(data.health.phase);
  oss << "\"health\":{\"phase\":\"" << json_escape(phase_name) << "\",\"components\":[";
  for (std::size_t i = 0; i < data.health.components.size(); ++i) {
    const auto& component = data.health.components[i];
    if (i > 0) {
      oss << ",";
    }
    oss << "{\"name\":\"" << json_escape(component.name) << "\","
        << "\"healthy\":" << (component.healthy ? "true" : "false") << ","
        << "\"state\":\"" << json_escape(component.state) << "\","
        << "\"detail\":\"" << json_escape(component.detail) << "\"}";
  }
  oss << "],";
  oss << "\"phase_name\":\"" << json_escape(phase_name) << "\",";
  oss << "\"detail\":\"" << json_escape(data.health.detail) << "\"},";
  oss << "\"preview\":[";
  for (std::size_t i = 0; i < data.preview_detections.size(); ++i) {
    if (i > 0) {
      oss << ",";
    }
    oss << "\"" << json_escape(format_detection_preview(data.preview_detections[i])) << "\"";
  }
  oss << "]}";
  return oss.str();
}

std::string render_debug_dashboard_html(const DebugDashboardData& data) {
  std::ostringstream oss;
  oss << "<!doctype html><html><head><meta charset=\"utf-8\"><title>Robot Life Debug UI</title>";
  oss << "<style>"
      << "body{font-family:ui-sans-serif,system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:16px;}"
      << ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}"
      << ".card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:12px;}"
      << "h1{font-size:20px;margin:0 0 12px;}h2{font-size:13px;margin:0 0 8px;color:#8b949e;text-transform:uppercase;}"
      << ".metric{font-size:24px;font-weight:700;}ul{margin:0;padding-left:18px;}code{color:#7ee787;}"
      << ".pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#21262d;margin-right:6px;}"
      << "</style></head><body>";
  oss << "<h1>Robot Life Debug UI</h1>";
  oss << "<div class=\"grid\">";
  oss << "<section class=\"card\"><h2>Load</h2><div class=\"metric\">" << html_escape(to_string(data.load_shed.pressure))
      << "</div><div>" << html_escape(data.load_shed.reason) << "</div>"
      << "<div>batch cap: " << data.load_shed.max_events_per_batch << "</div>"
      << "<div>preview every " << data.load_shed.preview_every_ticks << " ticks</div></section>";
  oss << "<section class=\"card\"><h2>Runtime</h2><div>pending: <span class=\"metric\">" << data.runtime.pending_events
      << "</span></div><div>stable: " << data.runtime.stable_events_last_tick
      << "</div><div>scenes: " << data.runtime.scene_candidates_last_tick << "</div></section>";
  oss << "<section class=\"card\"><h2>Backend</h2><div class=\"metric\">" << html_escape(data.backend.backend_id)
      << "</div><div>batches: " << data.backend.delivered_batches << "</div><div>detections: "
      << data.backend.delivered_detections << "</div></section>";
  oss << "<section class=\"card\"><h2>System</h2><div>platform: " << html_escape(data.platform) << "</div>"
      << "<div>gpu: " << html_escape(data.gpu_summary) << "</div>"
      << "<div>memory: " << data.process_memory_mb << " MB</div></section>";
  if (data.runtime.last_decision.has_value()) {
    oss << "<section class=\"card\"><h2>Final Scene Output</h2><div class=\"metric\">"
        << html_escape(data.runtime.last_decision->target_behavior) << "</div><div>"
        << html_escape(data.runtime.last_decision->reason) << "</div></section>";
  }
  oss << "<section class=\"card\"><h2>Branch Config</h2>";
  for (const auto& [branch_id, enabled] : data.tuning.branch_enabled) {
    oss << "<div><span class=\"pill\">" << html_escape(perception::to_string(branch_id)) << "</span>"
        << (enabled ? "enabled" : "disabled")
        << " interval=" << data.tuning.branch_intervals.at(branch_id) << "</div>";
  }
  oss << "</section>";
  oss << "<section class=\"card\"><h2>Preview Side Channel</h2><ul>";
  if (data.preview_detections.empty()) {
    oss << "<li>no preview detections</li>";
  } else {
    for (const auto& detection : data.preview_detections) {
      oss << "<li>" << html_escape(format_detection_preview(detection)) << "</li>";
    }
  }
  oss << "</ul></section>";
  oss << "<section class=\"card\"><h2>Telemetry</h2><ul>";
  for (const auto& [stage, aggregate] : data.telemetry) {
    oss << "<li><strong>" << html_escape(stage) << "</strong>: count=" << aggregate.count;
    if (aggregate.avg_duration_ms.has_value()) {
      oss << " avg=" << *aggregate.avg_duration_ms << "ms";
    }
    oss << "</li>";
  }
  oss << "</ul></section>";
  oss << "</div></body></html>";
  return oss.str();
}

bool write_debug_dashboard_files(
    const DebugDashboardData& data,
    const std::filesystem::path& html_path,
    const std::filesystem::path& json_path) {
  std::ofstream html(html_path);
  std::ofstream json(json_path);
  if (!html.good() || !json.good()) {
    return false;
  }
  auto final_data = data;
  final_data.process_memory_mb = process_memory_mb();
  html << render_debug_dashboard_html(final_data);
  json << render_debug_dashboard_json(final_data);
  return true;
}

}  // namespace robot_life_cpp::runtime
