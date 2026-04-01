import cv2
import time
import numpy as np

def test_camera():
    print("Scanning for working Mac cameras...")
    for backend in [cv2.CAP_ANY, cv2.CAP_AVFOUNDATION]:
        backend_name = "AVFOUNDATION" if backend == cv2.CAP_AVFOUNDATION else "ANY"
        for i in range(3):
            print(f"Testing device {i} with backend {backend_name}...")
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                print(f"Device {i} failed to open.")
                continue
            
            # Read a few frames to let auto-exposure adjust
            success = False
            for j in range(10):
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    mean_val = np.mean(frame)
                    if mean_val > 5.0:  # Not completely pitch black
                        print(f"[SUCCESS] Device {i} with {backend_name} successfully delivered frames! (Brightness: {mean_val:.1f})")
                        success = True
                        break
                time.sleep(0.1)
                
            cap.release()
            if success:
                return
    print("[ERROR] None of the camera devices could produce a valid frame.")

if __name__ == "__main__":
    test_camera()
