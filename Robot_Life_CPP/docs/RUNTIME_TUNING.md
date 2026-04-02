# Runtime Tuning

## Goal

Keep runtime-sensitive parameters in one validated config so scene logic and perception sampling can be tuned without code edits.

## Source of Truth

- Config file: `configs/runtime_tuning.yaml`
- Supported profile names:
  - `mac_debug_native`
  - `linux_deepstream_4vision`
  - `linux_cpu_fallback_safe`
  - aliases: `cpu_debug`, `deepstream_prod`, `fallback_safe`

## What Lives Here

- `live_loop.*`
  - `tick_hz`
  - `max_pending_events`
  - `drop_when_full`
- `event_injector.*`
  - `dedupe_window_s`
  - `cooldown_window_s`
  - `max_events_per_batch`
- `stabilizer.*`
  - `debounce_count`
  - `debounce_window_s`
  - `cooldown_s`
  - `hysteresis_threshold`
  - `hysteresis_transition_high`
  - `hysteresis_transition_low`
  - `dedup_window_s`
- `aggregator.*`
  - `scene_ttl_s`
  - `score_decay_s`
  - `scene_bias.<scene_type>`
- `taxonomy.*`
  - `default_scene`
  - `event_scene_exact.<event_type>`
  - `event_scene_token.<token>`
  - `proactive_scenes`
  - `safety_scenes`
  - `attention_scenes`
  - `engagement_scenes`
  - `noticed_scenes`
  - `notice_events`
  - `mutual_events`
  - `engagement_events`
  - `social_behaviors`
- `arbitrator.*`
  - `decision_cooldown_s`
  - `scene_priority.<scene_type>`
  - `behavior_by_scene.<scene_type>`
- `deepstream.*`
  - `share_preprocess`
  - `share_tracker`
  - `max_detections_per_frame`
  - `<branch>.enabled`
  - `<branch>.sample_interval_frames`

## Runtime Path

- `run-live` loads the selected profile from `configs/runtime_tuning.yaml`
- the launcher applies tuning to:
  - `LiveLoop`
  - `DetectionEventInjector`
- taxonomy-backed runtime behavior:
  - `SceneAggregator` event -> scene classification
  - `CooldownManager` proactive scene grouping
  - `LifeState` scene/event grouping flags
- `deepstream-backend` applies tuning to:
  - branch enable flags
  - branch sampling intervals
  - shared preprocess / tracker settings
  - max detections per frame

## Hot Reload

- `run-live` supports validated reload through `RuntimeTuningStore`
- default behavior checks the tuning file every tick
- on a valid file change:
  - live loop rules are replaced safely
  - injector dedupe/cooldown windows are updated
  - invalid configs are rejected and the previous good config remains active

## Current Boundary

- This config is the single source of truth for tuning values in the C++ runtime.
- UI sliders are not wired yet; they should eventually write to this config or a validated API backed by the same schema.
- Linux + NVIDIA hardware validation is still required for production DeepStream behavior.
