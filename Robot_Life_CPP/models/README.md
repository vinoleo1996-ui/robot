# Model Store Layout

This directory is the single model root expected by the current development and deployment profiles.

Recommended layout:

- `models/native`: CPU or native development assets
- `models/deepstream`: DeepStream/TensorRT deployment assets

DeepStream integration should keep branch-specific assets under `models/deepstream` and avoid scattering model paths across launch scripts.
