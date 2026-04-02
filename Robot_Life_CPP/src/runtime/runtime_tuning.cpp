#include "robot_life_cpp/runtime/runtime_tuning.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::runtime {

namespace {
std::string trim_copy(std::string value) {
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(),
                           [](unsigned char c) { return !std::isspace(c); }));
  value.erase(std::find_if(value.rbegin(), value.rend(),
                           [](unsigned char c) { return !std::isspace(c); })
                  .base(),
              value.end());
  return value;
}

std::string lowercase_copy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

std::unordered_map<std::string, std::string> load_yaml_like(
    const std::filesystem::path& path,
    std::string* error) {
  std::unordered_map<std::string, std::string> out{};
  std::ifstream fin(path);
  if (!fin.good()) {
    if (error != nullptr) {
      *error = "cannot open runtime tuning config: " + path.string();
    }
    return out;
  }

  std::string line{};
  while (std::getline(fin, line)) {
    const auto no_comment = line.substr(0, line.find('#'));
    const auto pos = no_comment.find(':');
    if (pos == std::string::npos) {
      continue;
    }
    auto key = trim_copy(no_comment.substr(0, pos));
    auto value = trim_copy(no_comment.substr(pos + 1));
    if (!key.empty()) {
      out[key] = value;
    }
  }
  if (error != nullptr) {
    error->clear();
  }
  return out;
}

bool parse_bool(const std::string& value, bool fallback) {
  const auto normalized = lowercase_copy(value);
  if (normalized == "1" || normalized == "true" || normalized == "yes" || normalized == "on") {
    return true;
  }
  if (normalized == "0" || normalized == "false" || normalized == "no" || normalized == "off") {
    return false;
  }
  return fallback;
}

int parse_int(const std::string& value, int fallback) {
  try {
    return std::stoi(value);
  } catch (...) {
    return fallback;
  }
}

double parse_double(const std::string& value, double fallback) {
  try {
    return std::stod(value);
  } catch (...) {
    return fallback;
  }
}

std::optional<common::EventPriority> parse_priority(const std::string& value) {
  const auto normalized = lowercase_copy(value);
  if (normalized == "p0") {
    return common::EventPriority::P0;
  }
  if (normalized == "p1") {
    return common::EventPriority::P1;
  }
  if (normalized == "p2") {
    return common::EventPriority::P2;
  }
  if (normalized == "p3") {
    return common::EventPriority::P3;
  }
  return std::nullopt;
}

std::string alias_profile_name(const std::string& profile_name) {
  if (profile_name == "cpu_debug") {
    return "mac_debug_native";
  }
  if (profile_name == "deepstream_prod") {
    return "linux_deepstream_4vision";
  }
  if (profile_name == "fallback_safe") {
    return "linux_cpu_fallback_safe";
  }
  return profile_name;
}

std::string key_for(const std::string& profile_name, std::string_view suffix) {
  return "profiles." + profile_name + "." + std::string(suffix);
}

void apply_branch_defaults(RuntimeTuningProfile* tuning) {
  if (tuning == nullptr) {
    return;
  }
  tuning->branch_enabled.try_emplace(perception::DeepStreamBranchId::Face, true);
  tuning->branch_enabled.try_emplace(perception::DeepStreamBranchId::PoseGesture, true);
  tuning->branch_enabled.try_emplace(perception::DeepStreamBranchId::Motion, true);
  tuning->branch_enabled.try_emplace(perception::DeepStreamBranchId::SceneObject, true);

  tuning->branch_intervals.try_emplace(perception::DeepStreamBranchId::Face, 1);
  tuning->branch_intervals.try_emplace(perception::DeepStreamBranchId::PoseGesture, 2);
  tuning->branch_intervals.try_emplace(perception::DeepStreamBranchId::Motion, 1);
  tuning->branch_intervals.try_emplace(perception::DeepStreamBranchId::SceneObject, 3);
}

std::unordered_set<std::string> parse_csv_set(
    const std::string& value,
    const std::unordered_set<std::string>& fallback) {
  std::unordered_set<std::string> out{};
  std::size_t start = 0;
  while (start <= value.size()) {
    const auto end = value.find(',', start);
    const auto item = trim_copy(value.substr(start, end == std::string::npos ? std::string::npos : end - start));
    if (!item.empty()) {
      out.insert(item);
    }
    if (end == std::string::npos) {
      break;
    }
    start = end + 1;
  }
  return out.empty() ? fallback : out;
}
}  // namespace

bool load_runtime_tuning_profile(
    const std::filesystem::path& path,
    const std::string& profile_name,
    RuntimeTuningProfile* out,
    std::string* error) {
  if (out == nullptr) {
    if (error != nullptr) {
      *error = "runtime tuning output is null";
    }
    return false;
  }

  const auto kv = load_yaml_like(path, error);
  if (kv.empty()) {
    return false;
  }

  RuntimeTuningProfile tuning{};
  tuning.profile_name = alias_profile_name(profile_name);
  apply_branch_defaults(&tuning);
  tuning.aggregator.taxonomy = tuning.taxonomy;

  const auto profile_key = tuning.profile_name;
  auto lookup = [&](std::string_view suffix) -> std::optional<std::string> {
    const auto it = kv.find(key_for(profile_key, suffix));
    if (it == kv.end()) {
      return std::nullopt;
    }
    return it->second;
  };

  if (const auto value = lookup("live_loop.tick_hz"); value.has_value()) {
    tuning.live_loop.tick_hz = std::max(1.0, parse_double(*value, tuning.live_loop.tick_hz));
  }
  if (const auto value = lookup("live_loop.max_pending_events"); value.has_value()) {
    tuning.live_loop.max_pending_events =
        static_cast<std::size_t>(std::max(1, parse_int(*value, static_cast<int>(tuning.live_loop.max_pending_events))));
  }
  if (const auto value = lookup("live_loop.drop_when_full"); value.has_value()) {
    tuning.live_loop.drop_when_full = parse_bool(*value, tuning.live_loop.drop_when_full);
  }

  if (const auto value = lookup("event_injector.dedupe_window_s"); value.has_value()) {
    tuning.event_injector.dedupe_window_s = std::max(0.0, parse_double(*value, tuning.event_injector.dedupe_window_s));
  }
  if (const auto value = lookup("event_injector.cooldown_window_s"); value.has_value()) {
    tuning.event_injector.cooldown_window_s =
        std::max(0.0, parse_double(*value, tuning.event_injector.cooldown_window_s));
  }
  if (const auto value = lookup("event_injector.max_events_per_batch"); value.has_value()) {
    tuning.event_injector.max_events_per_batch =
        static_cast<std::size_t>(std::max(1, parse_int(*value, static_cast<int>(tuning.event_injector.max_events_per_batch))));
  }

  if (const auto value = lookup("stabilizer.debounce_count"); value.has_value()) {
    tuning.stabilizer.debounce_count = std::max(1, parse_int(*value, tuning.stabilizer.debounce_count));
  }
  if (const auto value = lookup("stabilizer.debounce_window_s"); value.has_value()) {
    tuning.stabilizer.debounce_window_s = std::max(0.0, parse_double(*value, tuning.stabilizer.debounce_window_s));
  }
  if (const auto value = lookup("stabilizer.cooldown_s"); value.has_value()) {
    tuning.stabilizer.cooldown_s = std::max(0.0, parse_double(*value, tuning.stabilizer.cooldown_s));
  }
  if (const auto value = lookup("stabilizer.hysteresis_threshold"); value.has_value()) {
    tuning.stabilizer.hysteresis_threshold = std::clamp(parse_double(*value, tuning.stabilizer.hysteresis_threshold), 0.0, 1.0);
  }
  if (const auto value = lookup("stabilizer.hysteresis_transition_high"); value.has_value()) {
    tuning.stabilizer.hysteresis_transition_high =
        std::clamp(parse_double(*value, tuning.stabilizer.hysteresis_transition_high), 0.0, 1.0);
  }
  if (const auto value = lookup("stabilizer.hysteresis_transition_low"); value.has_value()) {
    tuning.stabilizer.hysteresis_transition_low =
        std::clamp(parse_double(*value, tuning.stabilizer.hysteresis_transition_low), 0.0, 1.0);
  }
  if (const auto value = lookup("stabilizer.dedup_window_s"); value.has_value()) {
    tuning.stabilizer.dedup_window_s = std::max(0.0, parse_double(*value, tuning.stabilizer.dedup_window_s));
  }

  if (const auto value = lookup("aggregator.scene_ttl_s"); value.has_value()) {
    tuning.aggregator.scene_ttl_s = std::max(0.3, parse_double(*value, tuning.aggregator.scene_ttl_s));
  }
  if (const auto value = lookup("aggregator.score_decay_s"); value.has_value()) {
    tuning.aggregator.score_decay_s = std::max(0.3, parse_double(*value, tuning.aggregator.score_decay_s));
  }

  if (const auto value = lookup("taxonomy.default_scene"); value.has_value() && !value->empty()) {
    tuning.taxonomy.default_scene = *value;
  }
  if (const auto value = lookup("taxonomy.proactive_scenes"); value.has_value()) {
    tuning.taxonomy.proactive_scenes = parse_csv_set(*value, tuning.taxonomy.proactive_scenes);
  }
  if (const auto value = lookup("taxonomy.safety_scenes"); value.has_value()) {
    tuning.taxonomy.safety_scenes = parse_csv_set(*value, tuning.taxonomy.safety_scenes);
  }
  if (const auto value = lookup("taxonomy.attention_scenes"); value.has_value()) {
    tuning.taxonomy.attention_scenes = parse_csv_set(*value, tuning.taxonomy.attention_scenes);
  }
  if (const auto value = lookup("taxonomy.engagement_scenes"); value.has_value()) {
    tuning.taxonomy.engagement_scenes = parse_csv_set(*value, tuning.taxonomy.engagement_scenes);
  }
  if (const auto value = lookup("taxonomy.noticed_scenes"); value.has_value()) {
    tuning.taxonomy.noticed_scenes = parse_csv_set(*value, tuning.taxonomy.noticed_scenes);
  }
  if (const auto value = lookup("taxonomy.notice_events"); value.has_value()) {
    tuning.taxonomy.notice_events = parse_csv_set(*value, tuning.taxonomy.notice_events);
  }
  if (const auto value = lookup("taxonomy.mutual_events"); value.has_value()) {
    tuning.taxonomy.mutual_events = parse_csv_set(*value, tuning.taxonomy.mutual_events);
  }
  if (const auto value = lookup("taxonomy.engagement_events"); value.has_value()) {
    tuning.taxonomy.engagement_events = parse_csv_set(*value, tuning.taxonomy.engagement_events);
  }
  if (const auto value = lookup("taxonomy.social_behaviors"); value.has_value()) {
    tuning.taxonomy.social_behaviors = parse_csv_set(*value, tuning.taxonomy.social_behaviors);
  }

  if (const auto value = lookup("arbitrator.decision_cooldown_s"); value.has_value()) {
    tuning.arbitrator.decision_cooldown_s =
        std::max(0.0, parse_double(*value, tuning.arbitrator.decision_cooldown_s));
  }

  if (const auto value = lookup("deepstream.share_preprocess"); value.has_value()) {
    tuning.share_preprocess = parse_bool(*value, tuning.share_preprocess);
  }
  if (const auto value = lookup("deepstream.share_tracker"); value.has_value()) {
    tuning.share_tracker = parse_bool(*value, tuning.share_tracker);
  }
  if (const auto value = lookup("deepstream.max_detections_per_frame"); value.has_value()) {
    tuning.max_detections_per_frame =
        static_cast<std::size_t>(std::max(1, parse_int(*value, static_cast<int>(tuning.max_detections_per_frame))));
  }

  for (const auto branch_id : {perception::DeepStreamBranchId::Face,
                               perception::DeepStreamBranchId::PoseGesture,
                               perception::DeepStreamBranchId::Motion,
                               perception::DeepStreamBranchId::SceneObject}) {
    const auto name = perception::to_string(branch_id);
    if (const auto value = lookup("deepstream." + name + ".enabled"); value.has_value()) {
      tuning.branch_enabled[branch_id] = parse_bool(*value, tuning.branch_enabled[branch_id]);
    }
    if (const auto value = lookup("deepstream." + name + ".sample_interval_frames"); value.has_value()) {
      tuning.branch_intervals[branch_id] = std::max(1, parse_int(*value, tuning.branch_intervals[branch_id]));
    }
  }

  for (const auto& [key, value] : kv) {
    const auto scene_bias_prefix = key_for(profile_key, "aggregator.scene_bias.");
    if (key.rfind(scene_bias_prefix, 0) == 0) {
      tuning.aggregator.scene_bias[key.substr(scene_bias_prefix.size())] =
          std::max(0.0, parse_double(value, 1.0));
      continue;
    }
    const auto event_scene_exact_prefix = key_for(profile_key, "taxonomy.event_scene_exact.");
    if (key.rfind(event_scene_exact_prefix, 0) == 0) {
      tuning.taxonomy.event_scene_exact[key.substr(event_scene_exact_prefix.size())] = value;
      continue;
    }
    const auto event_scene_token_prefix = key_for(profile_key, "taxonomy.event_scene_token.");
    if (key.rfind(event_scene_token_prefix, 0) == 0) {
      tuning.taxonomy.event_scene_token[key.substr(event_scene_token_prefix.size())] = value;
      continue;
    }
    const auto scene_priority_prefix = key_for(profile_key, "arbitrator.scene_priority.");
    if (key.rfind(scene_priority_prefix, 0) == 0) {
      if (const auto priority = parse_priority(value); priority.has_value()) {
        tuning.arbitrator.scene_priority[key.substr(scene_priority_prefix.size())] = *priority;
      }
      continue;
    }
    const auto behavior_prefix = key_for(profile_key, "arbitrator.behavior_by_scene.");
    if (key.rfind(behavior_prefix, 0) == 0) {
      tuning.arbitrator.behavior_by_scene[key.substr(behavior_prefix.size())] = value;
    }
  }

  tuning.aggregator.taxonomy = tuning.taxonomy;

  if (tuning.stabilizer.hysteresis_transition_low > tuning.stabilizer.hysteresis_transition_high) {
    if (error != nullptr) {
      *error = "invalid runtime tuning: hysteresis_transition_low > hysteresis_transition_high";
    }
    return false;
  }

  *out = std::move(tuning);
  if (error != nullptr) {
    error->clear();
  }
  return true;
}

void apply_runtime_tuning_to_graph(
    const RuntimeTuningProfile& tuning,
    perception::DeepStreamGraphConfig* config) {
  if (config == nullptr) {
    return;
  }
  config->share_preprocess = tuning.share_preprocess;
  config->share_tracker = tuning.share_tracker;
  config->max_detections_per_frame = std::max<std::size_t>(1, tuning.max_detections_per_frame);
  for (auto& branch : config->branches) {
    if (const auto it = tuning.branch_enabled.find(branch.id); it != tuning.branch_enabled.end()) {
      branch.enabled = it->second;
    }
    if (const auto it = tuning.branch_intervals.find(branch.id); it != tuning.branch_intervals.end()) {
      branch.sample_interval_frames = std::max(1, it->second);
    }
  }
}

RuntimeTuningStore::RuntimeTuningStore(std::filesystem::path path) : path_(std::move(path)) {}

bool RuntimeTuningStore::load(const std::string& profile_name, std::string* error) {
  RuntimeTuningProfile tuning{};
  if (!load_runtime_tuning_profile(path_, profile_name, &tuning, error)) {
    return false;
  }
  current_ = std::move(tuning);
  if (std::filesystem::exists(path_)) {
    last_write_time_ = std::filesystem::last_write_time(path_);
  }
  return true;
}

bool RuntimeTuningStore::reload_if_changed(
    const std::string& profile_name,
    bool* reloaded,
    std::string* error) {
  if (reloaded != nullptr) {
    *reloaded = false;
  }
  if (path_.empty() || !std::filesystem::exists(path_)) {
    if (error != nullptr) {
      *error = "runtime tuning path missing: " + path_.string();
    }
    return false;
  }
  const auto write_time = std::filesystem::last_write_time(path_);
  if (current_.has_value() && write_time == last_write_time_) {
    if (error != nullptr) {
      error->clear();
    }
    return true;
  }
  RuntimeTuningProfile tuning{};
  if (!load_runtime_tuning_profile(path_, profile_name, &tuning, error)) {
    return false;
  }
  current_ = std::move(tuning);
  last_write_time_ = write_time;
  if (reloaded != nullptr) {
    *reloaded = true;
  }
  return true;
}

const std::filesystem::path& RuntimeTuningStore::path() const { return path_; }

const std::optional<RuntimeTuningProfile>& RuntimeTuningStore::current() const { return current_; }

}  // namespace robot_life_cpp::runtime
