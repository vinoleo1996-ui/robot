#include "robot_life_cpp/behavior/resources.hpp"

#include <algorithm>
#include <limits>
#include <sstream>

namespace robot_life_cpp::behavior {

ResourceManager::ResourceManager() {
  resource_defs_.emplace("camera", ResourceDef{"camera", ResourceMode::Shared, 2});
  resource_defs_.emplace("audio", ResourceDef{"audio", ResourceMode::Exclusive, 2});
  resource_defs_.emplace("gpu", ResourceDef{"gpu", ResourceMode::Shared, 2});
  resource_defs_.emplace("AudioOut", ResourceDef{"AudioOut", ResourceMode::Exclusive, 3});
  resource_defs_.emplace("HeadMotion", ResourceDef{"HeadMotion", ResourceMode::Shared, 2});
  resource_defs_.emplace("BodyMotion", ResourceDef{"BodyMotion", ResourceMode::Shared, 2});
  resource_defs_.emplace("FaceExpression", ResourceDef{"FaceExpression", ResourceMode::Exclusive, 2});
  resource_defs_.emplace("AttentionTarget", ResourceDef{"AttentionTarget", ResourceMode::Shared, 1});
  resource_defs_.emplace("DialogContext", ResourceDef{"DialogContext", ResourceMode::Ducking, 2});
}

ResourceGrant ResourceManager::request_grant(
    const std::string& trace_id,
    const std::string& decision_id,
    const std::string& behavior_id,
    const std::vector<std::string>& required_resources,
    const std::vector<std::string>& optional_resources,
    int priority,
    int duration_ms,
    double now_mono_s) {
  cleanup_expired(now_mono_s);
  const auto end_time = now_mono_s + (static_cast<double>(std::max(1, duration_ms)) / 1000.0);

  const auto grant_id = common::new_id();
  std::vector<std::string> granted{};
  std::vector<std::string> denied{};
  std::vector<std::string> reasons{};
  std::unordered_map<std::string, std::vector<std::string>> preempt_plan{};

  for (const auto& resource : required_resources) {
    std::vector<std::string> preempt_grants{};
    if (!evaluate_allocation(resource, priority, now_mono_s, &preempt_grants)) {
      denied.push_back(resource);
      reasons.push_back(build_conflict_reason(resource, now_mono_s));
      continue;
    }
    preempt_plan.emplace(resource, std::move(preempt_grants));
  }

  if (!denied.empty()) {
    ResourceGrant denied_grant{};
    denied_grant.grant_id = grant_id;
    denied_grant.trace_id = trace_id;
    denied_grant.decision_id = decision_id;
    denied_grant.granted = false;
    denied_grant.denied_resources = std::move(denied);
    std::ostringstream oss;
    oss << "required_resources_denied";
    for (const auto& r : reasons) {
      oss << ":" << r;
    }
    denied_grant.reason = oss.str();
    return denied_grant;
  }

  for (const auto& resource : required_resources) {
    const auto it = preempt_plan.find(resource);
    const std::vector<std::string> preempt_grants = it == preempt_plan.end()
                                                        ? std::vector<std::string>{}
                                                        : it->second;
    allocate(
        resource,
        ResourceOwner{
            .grant_id = grant_id,
            .behavior_id = behavior_id,
            .priority = priority,
            .end_time = end_time,
        },
        preempt_grants);
    granted.push_back(resource);
  }

  for (const auto& resource : optional_resources) {
    std::vector<std::string> preempt_grants{};
    if (!evaluate_allocation(resource, priority, now_mono_s, &preempt_grants)) {
      continue;
    }
    allocate(
        resource,
        ResourceOwner{
            .grant_id = grant_id,
            .behavior_id = behavior_id,
            .priority = priority,
            .end_time = end_time,
        },
        preempt_grants);
    granted.push_back(resource);
  }

  ResourceGrant ok{};
  ok.grant_id = grant_id;
  ok.trace_id = trace_id;
  ok.decision_id = decision_id;
  ok.granted = true;
  ok.granted_resources = std::move(granted);
  ok.reason = ok.granted_resources.empty()
                  ? "no_resources_needed"
                  : "granted_" + std::to_string(ok.granted_resources.size()) + "_resources";
  active_grants_[grant_id] = ok;
  return ok;
}

void ResourceManager::release_grant(const std::string& grant_id) {
  auto grant_it = active_grants_.find(grant_id);
  if (grant_it == active_grants_.end()) {
    return;
  }
  for (auto it = owners_.begin(); it != owners_.end();) {
    auto& owners = it->second;
    owners.erase(
        std::remove_if(
            owners.begin(),
            owners.end(),
            [&](const ResourceOwner& owner) { return owner.grant_id == grant_id; }),
        owners.end());
    if (owners.empty()) {
      it = owners_.erase(it);
    } else {
      ++it;
    }
  }
  active_grants_.erase(grant_it);
}

void ResourceManager::force_release_all() {
  std::vector<std::string> grant_ids{};
  grant_ids.reserve(active_grants_.size());
  for (const auto& [grant_id, _] : active_grants_) {
    grant_ids.push_back(grant_id);
  }
  for (const auto& grant_id : grant_ids) {
    release_grant(grant_id);
  }
}

std::unordered_map<std::string, std::string> ResourceManager::get_resource_status(double now_mono_s) {
  cleanup_expired(now_mono_s);
  std::unordered_map<std::string, std::string> status{};
  for (const auto& [resource_name, def] : resource_defs_) {
    auto owners_it = owners_.find(resource_name);
    if (owners_it == owners_.end() || owners_it->second.empty()) {
      status[resource_name] = "free";
      continue;
    }
    std::vector<ResourceOwner> owners = owners_it->second;
    std::sort(
        owners.begin(),
        owners.end(),
        [](const ResourceOwner& lhs, const ResourceOwner& rhs) { return lhs.priority > rhs.priority; });
    std::ostringstream oss;
    oss << (def.mode == ResourceMode::Exclusive ? "owned_by_" : "shared_by_");
    bool first = true;
    for (const auto& owner : owners) {
      if (!first) {
        oss << "|";
      }
      first = false;
      const auto ttl_ms = std::max(0, static_cast<int>((owner.end_time - now_mono_s) * 1000.0));
      oss << owner.behavior_id << "(" << priority_label(owner.priority) << "," << ttl_ms << "ms)";
    }
    status[resource_name] = oss.str();
  }
  return status;
}

std::string ResourceManager::priority_label(int internal_priority) {
  if (internal_priority < 0 || internal_priority > 3) {
    return "internal_" + std::to_string(internal_priority);
  }
  return "P" + std::to_string(3 - internal_priority);
}

bool ResourceManager::evaluate_allocation(
    const std::string& resource_name,
    int priority,
    double now_mono_s,
    std::vector<std::string>* preempt_grants) {
  cleanup_expired(now_mono_s);
  const auto def_it = resource_defs_.find(resource_name);
  if (def_it == resource_defs_.end()) {
    return false;
  }
  auto owners_it = owners_.find(resource_name);
  if (owners_it == owners_.end() || owners_it->second.empty()) {
    return true;
  }

  auto& owners = owners_it->second;
  if (def_it->second.mode != ResourceMode::Exclusive) {
    return true;
  }

  int highest_owner_priority = std::numeric_limits<int>::min();
  for (const auto& owner : owners) {
    highest_owner_priority = std::max(highest_owner_priority, owner.priority);
  }
  if (priority <= highest_owner_priority) {
    return false;
  }
  if (preempt_grants != nullptr) {
    preempt_grants->clear();
    preempt_grants->reserve(owners.size());
    for (const auto& owner : owners) {
      preempt_grants->push_back(owner.grant_id);
    }
  }
  return true;
}

void ResourceManager::allocate(
    const std::string& resource_name,
    const ResourceOwner& owner,
    const std::vector<std::string>& preempt_grants) {
  for (const auto& preempt_id : preempt_grants) {
    remove_grant_from_resource(resource_name, preempt_id);
  }
  auto& owners = owners_[resource_name];
  const auto exists = std::find_if(
      owners.begin(),
      owners.end(),
      [&](const ResourceOwner& item) { return item.grant_id == owner.grant_id; });
  if (exists == owners.end()) {
    owners.push_back(owner);
  }
}

void ResourceManager::remove_grant_from_resource(
    const std::string& resource_name,
    const std::string& grant_id) {
  auto owners_it = owners_.find(resource_name);
  if (owners_it == owners_.end()) {
    return;
  }
  auto& owners = owners_it->second;
  owners.erase(
      std::remove_if(
          owners.begin(),
          owners.end(),
          [&](const ResourceOwner& owner) { return owner.grant_id == grant_id; }),
      owners.end());
  if (owners.empty()) {
    owners_.erase(owners_it);
  }

  auto grant_it = active_grants_.find(grant_id);
  if (grant_it != active_grants_.end()) {
    auto& granted_resources = grant_it->second.granted_resources;
    granted_resources.erase(
        std::remove(granted_resources.begin(), granted_resources.end(), resource_name),
        granted_resources.end());
    if (granted_resources.empty()) {
      active_grants_.erase(grant_it);
    }
  }
}

void ResourceManager::cleanup_expired(double now_mono_s) {
  for (auto it = owners_.begin(); it != owners_.end();) {
    auto& owners = it->second;
    owners.erase(
        std::remove_if(
            owners.begin(),
            owners.end(),
            [&](const ResourceOwner& owner) { return owner.end_time <= now_mono_s; }),
        owners.end());
    if (owners.empty()) {
      it = owners_.erase(it);
    } else {
      ++it;
    }
  }
}

std::string ResourceManager::build_conflict_reason(
    const std::string& resource_name,
    double now_mono_s) const {
  auto owners_it = owners_.find(resource_name);
  if (owners_it == owners_.end() || owners_it->second.empty()) {
    return resource_name + ":conflict";
  }
  std::ostringstream oss;
  oss << resource_name << ":owned_by_";
  bool first = true;
  for (const auto& owner : owners_it->second) {
    if (owner.end_time <= now_mono_s) {
      continue;
    }
    if (!first) {
      oss << ",";
    }
    first = false;
    oss << owner.behavior_id << "(" << priority_label(owner.priority) << ")";
  }
  return oss.str();
}

}  // namespace robot_life_cpp::behavior
