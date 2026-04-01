import sys
sys.path.append('src')
import numpy as np
from pathlib import Path
from robot_life.app import load_detector_config, build_pipeline_registry

cfg = load_detector_config(Path("configs/detectors/default.yaml"))
reg = build_pipeline_registry(["face", "gesture", "pose", "gaze", "motion", "audio"], cfg, mock_drivers=False)

print("Testing gesture...")
g = reg.get_pipeline("gesture")
if g:
    res = g.process({"camera": np.zeros((480, 640, 3), dtype=np.uint8)})
    print("Gesture output:", res)

print("Testing motion...")
m = reg.get_pipeline("motion")
if m:
    res2 = m.process({"camera": np.zeros((480, 640, 3), dtype=np.uint8)})
    print("Motion output:", res2)

print("SUCCESS")
