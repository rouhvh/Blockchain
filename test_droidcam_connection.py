#!/usr/bin/env python3
"""Test DroidCam connection và MediaPipe import"""

import os
import sys
import time
import cv2
import urllib.request
import socket

print("[TEST] Kiểm tra DroidCam + MediaPipe setup\n")
print("=" * 60)

# Test 1: MediaPipe import
print("\n[1] Test MediaPipe import...")
try:
    from mediapipe.tasks.python.core import base_options as mp_base_options
    from mediapipe.tasks.python.vision import face_landmarker as mp_face_landmarker
    from mediapipe.tasks.python.vision.core import image as mp_image
    from mediapipe.tasks.python.vision.core import vision_task_running_mode as mp_running_mode
    print("    [OK] MediaPipe Tasks API imported successfully")
    mp_available = True
except ImportError as e:
    print(f"    [ERROR] MediaPipe import failed: {e}")
    mp_available = False

# Test 2: DroidCam URL connection
print("\n[2] Test DroidCam URL connection...")
droidcam_url = os.environ.get('CAMERA_URL', 'http://172.20.10.2:4747/video/')
print(f"    URL: {droidcam_url}")

try:
    cap = cv2.VideoCapture(droidcam_url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    print("    [TEST] Attempting to read 3 frames...")
    success_count = 0
    for i in range(3):
        ret, frame = cap.read()
        if ret:
            success_count += 1
            print(f"    [OK] Frame {i+1}: {frame.shape}")
        else:
            print(f"    [FAIL] Frame {i+1}: Cannot read")
        time.sleep(0.1)
    
    cap.release()
    
    if success_count > 0:
        print(f"\n    [OK] DroidCam connection SUCCESS ({success_count}/3 frames)")
        droidcam_available = True
    else:
        print(f"\n    [ERROR] DroidCam connection FAILED - Cannot read frames")
        droidcam_available = False
        
except Exception as e:
    print(f"    [ERROR] DroidCam connection failed: {e}")
    droidcam_available = False

# Test 3: Fallback to webcam
if not droidcam_available:
    print("\n[3] Test fallback to local webcam 0...")
    try:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            print(f"    [OK] Local webcam 0 available: {frame.shape}")
        else:
            print(f"    [ERROR] Local webcam 0 failed")
    except Exception as e:
        print(f"    [ERROR] {e}")

# Summary
print("\n" + "=" * 60)
print("\n[SUMMARY]")
print(f"  MediaPipe:     {'[OK]' if mp_available else '[FAIL]'}")
print(f"  DroidCam:      {'[OK]' if droidcam_available else '[FAIL]'}")
print(f"  Fallback cam:  [OK]")

if mp_available and droidcam_available:
    print("\n✓ Ready to run: python importcv2.py")
elif mp_available:
    print("\n✓ Partially ready (using local camera)")
    print("  Tip: Check DroidCam IP and connection")
else:
    print("\n✗ MediaPipe not available - reinstall mediapipe?")
