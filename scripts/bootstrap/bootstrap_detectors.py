#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


MODEL_URLS = {
    "gesture_recognizer.task": (
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
        "gesture_recognizer/float16/1/gesture_recognizer.task"
    ),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
}

INSIGHTFACE_BUFFALO_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
)


def _download(url: str, target: Path, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        print(f"[skip] {target} already exists")
        return

    print(f"[downloading] {url}")
    with urlopen(url) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    print(f"[ok] saved -> {target}")


def _bootstrap_insightface_models(*, overwrite: bool) -> None:
    root = Path("~/.insightface/models").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    pack_dir = root / "buffalo_l"
    legacy_dir = root / "buffalo_l_legacy"

    if (legacy_dir / "det_10g.onnx").exists() and (legacy_dir / "w600k_r50.onnx").exists() and not overwrite:
        print(f"[skip] insightface legacy pack already exists: {legacy_dir}")
        return

    with tempfile.TemporaryDirectory(prefix="insightface_pack_") as tmp:
        zip_path = Path(tmp) / "buffalo_l.zip"
        _download(INSIGHTFACE_BUFFALO_URL, zip_path, overwrite=True)
        pack_dir.mkdir(parents=True, exist_ok=True)
        with ZipFile(zip_path, "r") as zf:
            zf.extractall(pack_dir)

    det_candidates = sorted(pack_dir.glob("det*.onnx"))
    rec_candidates = sorted(pack_dir.glob("*r50*.onnx"))
    if not det_candidates or not rec_candidates:
        print(f"[warn] insightface model pack incomplete under {pack_dir}")
        return

    legacy_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(det_candidates[0], legacy_dir / "det_10g.onnx")
    shutil.copy2(rec_candidates[0], legacy_dir / "w600k_r50.onnx")
    print(f"[ok] insightface legacy pack ready -> {legacy_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download detector models for local MVP runtime.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Project root path.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download model files even if they exist.",
    )
    parser.add_argument(
        "--with-insightface",
        action="store_true",
        help="Also download and prepare InsightFace model packs under ~/.insightface/models.",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    mediapipe_dir = root / "models" / "mediapipe"
    print(f"project_root={root}")
    print(f"target_dir={mediapipe_dir}")

    for filename, url in MODEL_URLS.items():
        _download(url, mediapipe_dir / filename, overwrite=args.overwrite)

    if args.with_insightface:
        _bootstrap_insightface_models(overwrite=args.overwrite)

    print("\nBootstrap complete.")
    print("To verify detector availability:")
    print("  python3 -m robot_life.app detector-status --config configs/runtime/local/local_mac_fast_reaction.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
