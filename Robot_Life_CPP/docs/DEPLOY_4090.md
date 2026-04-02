# Deploy on RTX 4090

## Goal

Run the full C++ migration workspace on Linux + RTX 4090 with CUDA acceleration enabled.

## Prerequisites

- Ubuntu 22.04+ (recommended)
- NVIDIA Driver `>= 550`
- CUDA Toolkit `12.x`
- CMake `>= 3.20`
- Ninja
- GCC/G++ `>= 11` or Clang `>= 15`

## Build

```bash
cd Robot_Life_CPP
./scripts/build_4090.sh
```

This script enables:

- `ROBOT_LIFE_CPP_ENABLE_CUDA=ON`
- `ROBOT_LIFE_CPP_BUILD_TESTS=ON`
- `ROBOT_LIFE_CPP_REQUIRE_CUDA=ON`

## Run

```bash
cd Robot_Life_CPP
./scripts/run_4090_full.sh
```

Expected startup output includes:

- CUDA runtime availability
- detected GPU devices
- migration progress (`implemented_modules/total_modules`)

If you need temporary CPU fallback:

```bash
cd Robot_Life_CPP
./scripts/run_cpu_full.sh
```

Before deploying on Linux, validate the repo baseline:

```bash
./scripts/doctor.sh
```

## Regression

```bash
cd Robot_Life_CPP
./scripts/regression.sh
```

Regression covers:

- configure + build
- core unit test (`test_core`)
- runtime smoke execution (`robot_life_cpp_main`)

## GPU/CPU placement baseline

- Face perception: GPU (`cuda:0`)
- Audio perception: GPU (`cuda:0`) + CPU fallback
- Pose perception: GPU (`cuda:0`)
- Motion perception: CPU (high-frequency, low-latency path)
- Event engine / runtime orchestration: CPU

UI is not part of this runtime critical path and must stay as an external debugging bridge.
