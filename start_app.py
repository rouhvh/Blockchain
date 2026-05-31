#!/usr/bin/env python3
"""Startup script for Drowsiness Detection with DroidCam"""

import os
import sys

# Set environment defaults
os.environ['DETECTION_MODE'] = os.environ.get('DETECTION_MODE', 'mediapipe')

camera_url_env = os.environ.get('CAMERA_URL', '').strip()
camera_index_env = os.environ.get('CAMERA_INDEX', '').strip()
force_local = os.environ.get('FORCE_LOCAL_CAMERA', '').strip().lower() in ('1', 'true', 'yes')

print("\n" + "="*60)
print("Drowsiness Detection System")
print("="*60)
print(f"Detection Mode: {os.environ['DETECTION_MODE']}")
if camera_url_env:
    print(f"Camera URL: {camera_url_env}")
else:
    idx = camera_index_env or 'auto'
    print(f"Camera Mode: Local webcam (index={idx}, FORCE_LOCAL_CAMERA={force_local})")
print("="*60 + "\n")

# Import and run
try:
    import importcv2
except KeyboardInterrupt:
    print("\n[INFO] Server stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n[ERROR] Failed to import importcv2: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# If import succeeded, start the server using importcv2.run_server()
try:
    if hasattr(importcv2, 'run_server'):
        importcv2.run_server()
    else:
        print('[WARN] importcv2.run_server() not available; you can run importcv2.py directly')
except KeyboardInterrupt:
    print("\n[INFO] Server stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n[ERROR] Failed to start server: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
