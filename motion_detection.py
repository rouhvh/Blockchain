"""Backward-compatible launcher for the Smart Traffic Safety app.

This file keeps the old filename available for anyone who still runs
`python motion_detection.py`, but the actual implementation now lives in
`importcv2.py`.
"""

from threading import Thread

from importcv2 import app, camera_stream, cap


if __name__ == '__main__':
    camera_thread = Thread(target=camera_stream, daemon=True)
    camera_thread.start()
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    finally:
        if cap.isOpened():
            cap.release()
