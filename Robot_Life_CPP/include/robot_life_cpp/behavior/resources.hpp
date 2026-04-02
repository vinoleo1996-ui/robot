#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "robot_life_cpp/common/schemas.hpp"

namespace robot_life_cpp::behavior {

enum class ResourceMode {
  Exclusive = 0,
  Shared = 1,
  Ducking = 2,
};

struct ResourceDef {
  std::string name;
  ResourceMode mode{ResourceMode::Shared};
  int priority_level{1};
};

struct ResourceOwner {
  std::string grant_id;
  std::string behavior_id;
  int priority{2};  // higher preempts lower
  double end_time{0.0};
};

struct ResourceGrant {
  std::string grant_id;
  std::string trace_id;
  std::string decision_id;
  bool granted{false};
  std::vector<std::string> granted_resources{};
  std::vector<std::string> denied_resources{};
  std::string reason;
};

class ResourceManager {
 public:
  ResourceManager();

  ResourceGrant request_grant(
      const std::string& trace_id,
      const std::string& decision_id,
      const std::string& behavior_id,
      const std::vector<std::string>& required_resources,
      const std::vector<std::string>& optional_resources,
      int priority = 2,
      int duration_ms = 5000,
      double now_mono_s = common::now_mono());

  void release_grant(const std::string& grant_id);
  void force_release_all();

  std::unordered_map<std::string, std::string> get_resource_status(
      double now_mono_s = common::now_mono());

 private:
  static std::string priority_label(int internal_priority);
  bool evaluate_allocation(
      const std::string& resource_name,
      int priority,
      double now_mono_s,
      std::vector<std::string>* preempt_grants);
  void allocate(
      const std::string& resource_name,
      const ResourceOwner& owner,
      const std::vector<std::string>& preempt_grants);
  void remove_grant_from_resource(const std::string& resource_name, const std::string& grant_id);
  void cleanup_expired(double now_mono_s);
  std::string build_conflict_reason(const std::string& resource_name, double now_mono_s) const;

  std::unordered_map<std::string, ResourceDef> resource_defs_{};
  std::unordered_map<std::string, std::vector<ResourceOwner>> owners_{};
  std::unordered_map<std::string, ResourceGrant> active_grants_{};
};

}  // namespace robot_life_cpp::behavior

