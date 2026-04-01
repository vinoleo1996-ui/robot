#!/usr/bin/env python3
"""
Integration helper for upgraded detectors (Whisper + YOLO Pose).

This script helps migrate from the original MVP (RMS/dB + MediaPipe 7 gestures)
to the upgraded version with Whisper ASR and YOLO Pose.

Steps:
  1. Install dependencies
  2. Validate GPU setup
  3. Download models
  4. Test individual detectors
  5. Run full MVP with upgraded config

Usage:
  python migrate_to_upgraded.py --all
  python migrate_to_upgraded.py --test-whisper
  python migrate_to_upgraded.py --test-yolo-pose
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_command(cmd: list[str], description: str) -> bool:
    """Run a shell command and return success status."""
    print(f"\n{'='*60}")
    print(f"📍 {description}")
    print(f"{'='*60}")
    print(f"$ {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Command failed: {e}")
        return False


def install_dependencies() -> bool:
    """Install required packages for upgraded detectors."""
    print("\n🔧 Installing upgraded detector dependencies...\n")
    
    commands = [
        (["pip", "install", "faster-whisper"], "Install faster-whisper (Whisper inference engine)"),
        (["pip", "install", "ultralytics"], "Install ultralytics (YOLO v8 framework)"),
        (["pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu118"],
         "Install/upgrade PyTorch with CUDA 11.8 support"),
    ]
    
    all_ok = True
    for cmd, desc in commands:
        if not run_command(cmd, desc):
            all_ok = False
            print(f"⚠️  Warning: Failed to run: {desc}")
    
    return all_ok


def validate_gpu() -> bool:
    """Validate GPU setup."""
    print("\n🖥️  Validating GPU setup...\n")
    
    try:
        import torch
        print(f"✅ PyTorch version: {torch.__version__}")
        print(f"✅ CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"✅ CUDA version: {torch.version.cuda}")
            print(f"✅ GPU: {torch.cuda.get_device_name(0)}")
            print(f"✅ GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
        else:
            print("⚠️  CUDA not available - will fall back to CPU (slower)")
        return True
    except ImportError:
        print("❌ PyTorch not found - install with: pip install torch")
        return False


def download_models() -> bool:
    """Download required model files."""
    print("\n📥 Downloading model files...\n")
    
    try:
        from ultralytics import YOLO
        print("📥 Downloading YOLOv8n-pose (first time, ~50MB)...")
        model = YOLO("yolov8n-pose.pt")
        print(f"✅ YOLOv8n-pose loaded: {model}")
        
        print("📥 Downloading Whisper models (handled by faster-whisper)...")
        print("   Models will be auto-downloaded on first use.")
        print("   tiny: 39MB, small: 244MB, medium: 769MB, large: 1.5GB")
        
        return True
    except Exception as e:
        print(f"❌ Failed to download models: {e}")
        return False


def test_whisper() -> bool:
    """Test Whisper ASR detector."""
    print("\n🎤 Testing Whisper ASR...\n")
    
    try:
        from robot_life.perception.adapters.whisper_adapter import WhisperASRDetector
        
        print("Initializing Whisper detector (small model)...")
        detector = WhisperASRDetector(config={
            "model_variant": "small",
            "device": "cuda",
            "compute_type": "float16",
        })
        detector.initialize()
        print("✅ Whisper detector initialized successfully")
        
        # Test with synthetic audio (2 seconds of silence)
        import numpy as np
        silence = np.zeros(32000, dtype=np.float32)  # 2s at 16kHz
        results = detector.process({"audio": silence})
        print(f"✅ Silence test: {len(results)} detections (expected 0)")
        
        detector.close()
        return True
    except Exception as e:
        print(f"❌ Whisper test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_yolo_pose() -> bool:
    """Test YOLO Pose gesture detector."""
    print("\n🎯 Testing YOLO Pose...\n")
    
    try:
        from robot_life.perception.adapters.yolo_pose_adapter import YOLOPoseGestureDetector
        import numpy as np
        
        print("Initializing YOLO Pose detector...")
        detector = YOLOPoseGestureDetector(config={
            "model_path": "yolov8n-pose.pt",
            "device": "cuda:0",
            "conf_threshold": 0.5,
        })
        detector.initialize()
        print("✅ YOLO Pose detector initialized successfully")
        
        # Test with blank frame
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        results = detector.process(blank_frame)
        print(f"✅ Blank frame test: {len(results)} detections (expected 0)")
        
        detector.close()
        return True
    except Exception as e:
        print(f"❌ YOLO Pose test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def benchmark_models() -> None:
    """Benchmark inference latency of upgraded models."""
    print("\n⏱️  Benchmarking model latencies...\n")
    
    import time
    import numpy as np
    
    # Whisper benchmark
    try:
        from faster_whisper import WhisperModel
        print("Benchmarking Whisper (small)...")
        model = WhisperModel("small", device="cuda", compute_type="float16")
        
        # Generate synthetic 3-second audio
        duration_s = 3
        sample_rate = 16000
        audio = np.sin(2 * np.pi * 440 * np.arange(duration_s * sample_rate) / sample_rate).astype(np.float32)
        
        start = time.time()
        segments, info = model.transcribe(audio, language="zh")
        elapsed = time.time() - start
        
        print(f"  ✅ 3s audio: {elapsed:.2f}s ({3/elapsed:.1f}x realtime)")
    except Exception as e:
        print(f"  ❌ Whisper benchmark failed: {e}")
    
    # YOLO Pose benchmark
    try:
        from ultralytics import YOLO
        print("Benchmarking YOLO Pose...")
        model = YOLO("yolov8n-pose.pt")
        
        # Generate synthetic image
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        start = time.time()
        _ = model.predict(frame, verbose=False, device="cuda:0")
        elapsed = time.time() - start
        
        print(f"  ✅ 640x480 frame: {elapsed*1000:.1f}ms")
    except Exception as e:
        print(f"  ❌ YOLO Pose benchmark failed: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate to upgraded detectors (Whisper + YOLO Pose)"
    )
    parser.add_argument("--all", action="store_true", help="Run all migration steps")
    parser.add_argument("--install", action="store_true", help="Install dependencies only")
    parser.add_argument("--validate-gpu", action="store_true", help="Validate GPU setup")
    parser.add_argument("--download-models", action="store_true", help="Download model files")
    parser.add_argument("--test-whisper", action="store_true", help="Test Whisper detector")
    parser.add_argument("--test-yolo-pose", action="store_true", help="Test YOLO Pose detector")
    parser.add_argument("--benchmark", action="store_true", help="Benchmark model latencies")
    
    args = parser.parse_args()
    
    if not any([args.all, args.install, args.validate_gpu, args.download_models,
                args.test_whisper, args.test_yolo_pose, args.benchmark]):
        parser.print_help()
        return 1
    
    print("""
╔════════════════════════════════════════════════════════════╗
║         robot_life_dev Upgraded Detector Installer          ║
║        (Whisper ASR + YOLO Pose Migration Helper)          ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    success = True
    
    if args.all or args.install:
        if not install_dependencies():
            success = False
    
    if args.all or args.validate_gpu:
        if not validate_gpu():
            success = False
    
    if args.all or args.download_models:
        if not download_models():
            success = False
    
    if args.all or args.test_whisper:
        if not test_whisper():
            success = False
    
    if args.all or args.test_yolo_pose:
        if not test_yolo_pose():
            success = False
    
    if args.all or args.benchmark:
        benchmark_models()
    
    print("\n" + "="*60)
    if success:
        print("✅ Migration preparation complete!")
        print("\nNext steps:")
        print("  1. Update configs/detectors/default.yaml to use upgraded.yaml")
        print("  2. Run: python scripts/validate/validate_4090.py --upgraded")
        print("  3. Monitor GPU: nvidia-smi -l 1")
    else:
        print("❌ Some steps failed - check errors above")
    print("="*60 + "\n")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
