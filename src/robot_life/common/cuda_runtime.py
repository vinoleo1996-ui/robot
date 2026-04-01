"""CUDA runtime bootstrap helpers for local wheel-based deployments."""

from __future__ import annotations

import ctypes
import os
import site
import sys
from pathlib import Path


def _candidate_nvidia_roots() -> list[Path]:
    roots: set[Path] = set()

    for entry in sys.path:
        if not entry:
            continue
        candidate = Path(entry).expanduser() / "nvidia"
        if candidate.is_dir():
            roots.add(candidate.resolve())

    try:
        user_site = Path(site.getusersitepackages()) / "nvidia"
        if user_site.is_dir():
            roots.add(user_site.resolve())
    except Exception:
        pass

    try:
        for package_dir in site.getsitepackages():
            candidate = Path(package_dir) / "nvidia"
            if candidate.is_dir():
                roots.add(candidate.resolve())
    except Exception:
        pass

    home_fallback = (
        Path.home()
        / ".local"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
        / "nvidia"
    )
    if home_fallback.is_dir():
        roots.add(home_fallback.resolve())

    return sorted(roots)


def discover_cuda_lib_dirs() -> list[Path]:
    """Return candidate CUDA shared-library directories from pip nvidia wheels."""
    dirs: list[Path] = []
    seen: set[Path] = set()
    for root in _candidate_nvidia_roots():
        for lib_dir in sorted(root.glob("*/lib")):
            if lib_dir.is_dir():
                resolved = lib_dir.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    dirs.append(resolved)
    return dirs


def prepend_cuda_library_path() -> list[Path]:
    """
    Prepend discovered CUDA library dirs to LD_LIBRARY_PATH.

    Note:
    - This is still useful for child processes.
    - For the current process, prefer `preload_cuda_shared_libs()` to guarantee symbol resolution.
    """
    lib_dirs = discover_cuda_lib_dirs()
    if not lib_dirs:
        return []

    existing = os.environ.get("LD_LIBRARY_PATH", "")
    existing_parts = [part for part in existing.split(":") if part]
    existing_set = set(existing_parts)
    new_parts = [str(path) for path in lib_dirs if str(path) not in existing_set]
    if new_parts:
        os.environ["LD_LIBRARY_PATH"] = ":".join(new_parts + existing_parts)
    return lib_dirs


def preload_cuda_shared_libs() -> tuple[int, int]:
    """
    Load CUDA `.so` files with RTLD_GLOBAL so ORT/llama can resolve dependencies.

    Returns:
      (loaded_count, failed_count)
    """
    loaded = 0
    failed = 0
    seen: set[Path] = set()

    for lib_dir in discover_cuda_lib_dirs():
        for so_path in sorted(lib_dir.glob("*.so*")):
            resolved = so_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                ctypes.CDLL(str(resolved), mode=ctypes.RTLD_GLOBAL)
                loaded += 1
            except OSError:
                failed += 1
    return loaded, failed


def ensure_cuda_runtime_loaded() -> tuple[int, int]:
    """Best-effort CUDA runtime bootstrap for the current process."""
    prepend_cuda_library_path()
    return preload_cuda_shared_libs()
