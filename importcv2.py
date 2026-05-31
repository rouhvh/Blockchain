from flask import Flask, render_template, Response, jsonify, request, send_from_directory
import cv2
import numpy as np
import time
import datetime
import os
import json
import platform
import urllib.request

from threading import Thread, Lock
from http_stream_reader import create_camera_stream
from functools import wraps

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from mediapipe.tasks.python.core import base_options as mp_base_options
    from mediapipe.tasks.python.vision import face_landmarker as mp_face_landmarker
    from mediapipe.tasks.python.vision.core import image as mp_image
    from mediapipe.tasks.python.vision.core import vision_task_running_mode as mp_running_mode
except ImportError as e:
    print(f"[DEBUG] MediaPipe import error: {e}")
    mp_base_options = None
    mp_face_landmarker = None
    mp_image = None
    mp_running_mode = None

# Blockchain & Identity Management
from blockchain import DrowsinessBlockchain
from user_identity import UserIdentityManager

app = Flask(__name__)

DEBUG_LOG = True

# Khởi tạo blockchain và user manager
blockchain = DrowsinessBlockchain(difficulty=1)
user_manager = UserIdentityManager()

# Global session variables
current_user_id = None
current_user_token = None

# URL của camera (có thể ghi đè bằng biến môi trường CAMERA_URL)
# Default: None -> prefer local laptop camera. To force local camera probing we set FORCE_LOCAL_CAMERA.
CAMERA_URL = os.environ.get('CAMERA_URL', '') or None
# Force using local webcam by default
os.environ['FORCE_LOCAL_CAMERA'] = os.environ.get('FORCE_LOCAL_CAMERA', '1')

# Mở capture với HTTP stream reader (tự động fallback về webcam 0)
cap, is_http_reader = create_camera_stream(CAMERA_URL, use_http_reader=True, width=320, height=240)

# Check nếu camera không mở được
is_opened = cap.is_opened() if is_http_reader else cap.isOpened()
if not is_opened:
    print(f"Warning: Failed to open camera stream, retrying with fallback...")
    cap, is_http_reader = create_camera_stream(None, width=320, height=240)
    # Re-check after fallback; if still not opened, exit program (no laptop camera available)
    if cap is None:
        print("Error: No camera device found (cap is None). Exiting.")
        import sys
        sys.exit(1)
    is_opened = cap.is_opened() if is_http_reader else cap.isOpened()
    if not is_opened:
        print("Error: Could not open any camera (HTTP stream and local fallback failed). Exiting.")
        import sys
        sys.exit(1)

# Load Haar Cascade để phát hiện mắt
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# Thông số
fps = 25
width, height = 320, 240
video_frame = None
lock = Lock()
capture_path = "captured_images"
os.makedirs(capture_path, exist_ok=True)

EYE_AR_THRESH = 15  # Ngưỡng khoảng cách giữa mí trên và dưới (tăng để phù hợp với webcam)
last_capture_time = None
capture_interval = 2
EYE_CLOSED_DURATION_THRESHOLD = 2.0  # seconds to trigger alert
closed_accum = 0.0
last_frame_ts = None
# Local flag to remember if we notified ESP32 about an active alert
esp32_alert_sent = False

DETECTION_MODE = os.environ.get("DETECTION_MODE", "mediapipe").strip().lower()
YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH", "models/drowsiness_yolov8.pt")
YOLO_IMAGE_SIZE = int(os.environ.get("YOLO_IMAGE_SIZE", "640"))
YOLO_DROWSY_LABELS = {"closed", "yawning", "distracted"}
MEDIAPIPE_EAR_THRESHOLD = float(os.environ.get("MEDIAPIPE_EAR_THRESHOLD", "0.21"))
FACE_LANDMARKER_MODEL_URL = os.environ.get(
    "FACE_LANDMARKER_MODEL_URL",
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
)
FACE_LANDMARKER_MODEL_PATH = os.environ.get(
    "FACE_LANDMARKER_MODEL_PATH",
    os.path.join("models", "face_landmarker_v2.task"),
)
ESP32_ALERT_URL = os.environ.get("ESP32_ALERT_URL", "").strip().rstrip("/")
ESP32_VEHICLE_STOP_ON_ALERT = os.environ.get("ESP32_VEHICLE_STOP_ON_ALERT", "1").strip().lower() not in ("0", "false", "no")

# Arduino settings (optional)
ARDUINO_PORT = os.environ.get("ARDUINO_PORT", "").strip()
ARDUINO_BAUD = int(os.environ.get("ARDUINO_BAUD", "9600") or 9600)
ARDUINO_AUTO_DETECT = os.environ.get("ARDUINO_AUTO_DETECT", "1").strip().lower() not in ("0", "false", "no")

try:
    from arduino_interface import ArduinoInterface
    arduino = None
    if ARDUINO_PORT or ARDUINO_AUTO_DETECT:
        try:
            arduino = ArduinoInterface(port=ARDUINO_PORT or None, baud=ARDUINO_BAUD, autoconnect=True)
            if DEBUG_LOG:
                print(f"[Arduino] connected on {arduino.port}")
        except Exception as e:
            if DEBUG_LOG:
                print(f"[Arduino] connection failed: {e}")
            arduino = None
except Exception as e:
    if DEBUG_LOG:
        print(f"[Arduino] module load failed: {e}")
    arduino = None

# ESP32 discovery helpers
esp32_endpoints = {
    'status': '/status',
    'events': '/events',
    'vehicle_stop': '/vehicle/stop',
    'vehicle_start': '/vehicle/start',
}
esp32_available = False
esp32_supports_vehicle_stop = False

def probe_esp32():
    global esp32_available, esp32_supports_vehicle_stop
    if not ESP32_ALERT_URL:
        esp32_available = False
        esp32_supports_vehicle_stop = False
        return
    try:
        # check status first (safe)
        url = ESP32_ALERT_URL.rstrip('/') + esp32_endpoints['status']
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = resp.read().decode('utf-8', errors='ignore')
        esp32_available = True
    except Exception as exc:
        if DEBUG_LOG:
            print(f"[ESP32] status probe failed: {exc}")
        esp32_available = False
        esp32_supports_vehicle_stop = False
        return

    # check vehicle/stop existence (safe GET returns status JSON)
    try:
        url2 = ESP32_ALERT_URL.rstrip('/') + esp32_endpoints['vehicle_stop']
        with urllib.request.urlopen(url2, timeout=2) as resp:
            _ = resp.read().decode('utf-8', errors='ignore')
        esp32_supports_vehicle_stop = True
    except Exception:
        esp32_supports_vehicle_stop = False

# Probe on import/startup
probe_esp32()


def fetch_remote_json(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
        return True, json.loads(payload)
    except Exception as exc:
        return False, str(exc)


def require_login(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        active = current_user_id or session.get('user_id')
        if not active:
            # If request expects JSON, return JSON error, otherwise redirect to login page
            if request.accept_mimetypes.accept_json or request.is_json:
                return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped


def require_role(role):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            active = current_user_id or session.get('user_id')
            if not active:
                if request.accept_mimetypes.accept_json or request.is_json:
                    return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
                return redirect(url_for('login'))
            raw = user_manager.get_raw_user(active)
            user_role = raw.get('role', 'manager') if raw else 'manager'
            if role == 'manager' and user_role in ('manager', 'admin'):
                return f(*args, **kwargs)
            if user_role != role:
                return jsonify({'success': False, 'message': 'Không đủ quyền truy cập'}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator

LEFT_EYE_LANDMARKS = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_LANDMARKS = [362, 385, 387, 263, 373, 380]

mp_face_mesh = None
face_landmarker = None
if DETECTION_MODE == "mediapipe":
    if mp_face_landmarker is None or mp_base_options is None or mp_image is None or mp_running_mode is None:
        print("Warning: MediaPipe Tasks API is not available, falling back to Haar cascade mode.")
        DETECTION_MODE = "haar"
    else:
        try:
            os.makedirs(os.path.dirname(FACE_LANDMARKER_MODEL_PATH) or ".", exist_ok=True)
            if not os.path.exists(FACE_LANDMARKER_MODEL_PATH):
                print(f"Downloading MediaPipe face landmarker model to {FACE_LANDMARKER_MODEL_PATH}...")
                urllib.request.urlretrieve(FACE_LANDMARKER_MODEL_URL, FACE_LANDMARKER_MODEL_PATH)

            face_landmarker_options = mp_face_landmarker.FaceLandmarkerOptions(
                base_options=mp_base_options.BaseOptions(model_asset_path=FACE_LANDMARKER_MODEL_PATH),
                running_mode=mp_running_mode.VisionTaskRunningMode.VIDEO,
                num_faces=1,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            face_landmarker = mp_face_landmarker.FaceLandmarker.create_from_options(face_landmarker_options)
            print("Loaded MediaPipe Face Landmarker for eye-closure detection.")
        except Exception as exc:
            print(f"Warning: could not initialize MediaPipe Face Landmarker: {exc}")
            print("Warning: falling back to Haar cascade mode.")
            DETECTION_MODE = "haar"

yolo_model = None
if DETECTION_MODE == "yolov8":
    if YOLO is None:
        print("Warning: ultralytics is not installed, falling back to Haar cascade mode.")
        DETECTION_MODE = "haar"
    else:
        try:
            yolo_model = YOLO(YOLO_MODEL_PATH)
            print(f"Loaded YOLOv8 model: {YOLO_MODEL_PATH}")
        except Exception as exc:
            print(f"Warning: could not load YOLOv8 model {YOLO_MODEL_PATH!r}: {exc}")
            print("Warning: falling back to Haar cascade mode.")
            DETECTION_MODE = "haar"

# Alert helper
if platform.system() == 'Windows':
    try:
        import winsound
    except Exception:
        winsound = None
else:
    winsound = None


def play_alert():
    try:
        if winsound:
            # frequency, duration(ms)
            winsound.Beep(1000, 700)
        else:
            # fallback: terminal bell
            print('\a')
        # local beep only; network/device alerts handled by trigger_alerts()
    except Exception as e:
        print(f"Alert failed: {e}")


def trigger_alerts(image_path: str = None, alert_level: str = "high"):
    """Central alert handler: local beep, then notify ESP32 and Arduino if available.

    image_path: optional path to saved frame for logging/signing
    alert_level: 'high'|'medium' etc.
    """
    # Local audible/visual alert
    try:
        play_alert()
    except Exception as e:
        if DEBUG_LOG:
            print(f"[Alert] play_alert failed: {e}")

    # Notify ESP32: drowsiness should stop vehicle and trigger audible alert.
    if ESP32_ALERT_URL and esp32_available:
        try:
            alert_mode = str(alert_level).strip().lower()
            if alert_mode in ("danger", "high"):
                url = f"{ESP32_ALERT_URL.rstrip('/')}/alert/danger"
            elif esp32_supports_vehicle_stop and ESP32_VEHICLE_STOP_ON_ALERT:
                url = f"{ESP32_ALERT_URL.rstrip('/')}{esp32_endpoints['vehicle_stop']}"
            else:
                url = f"{ESP32_ALERT_URL.rstrip('/')}/alert/on"
            try:
                urllib.request.urlopen(url, timeout=2).read()
                if DEBUG_LOG:
                    print(f"[ESP32] called {url}")
            except Exception as exc:
                if DEBUG_LOG:
                    print(f"[ESP32] call failed: {exc}")
        except Exception as exc:
            if DEBUG_LOG:
                print(f"[ESP32] unexpected error: {exc}")

    # Notify Arduino (buzzer) via serial
    if arduino:
        try:
            arduino.send_command("ALARM")
            if DEBUG_LOG:
                print(f"[Arduino] ALARM sent to {arduino.port}")
        except Exception as exc:
            if DEBUG_LOG:
                print(f"[Arduino] send failed: {exc}")


def infer_yolo_label(frame):
    if yolo_model is None:
        return None, 0.0

    try:
        result = yolo_model.predict(frame, imgsz=YOLO_IMAGE_SIZE, verbose=False)[0]
    except Exception as exc:
        print(f"Warning: YOLOv8 inference failed: {exc}")
        return None, 0.0

    if getattr(result, "probs", None) is not None:
        class_id = int(result.probs.top1)
        confidence = float(result.probs.top1conf)
        label = result.names.get(class_id, str(class_id))
        return label, confidence

    boxes = getattr(result, "boxes", None)
    if boxes is not None and len(boxes) > 0:
        confidences = boxes.conf.tolist()
        class_ids = boxes.cls.tolist()
        best_index = int(np.argmax(confidences))
        class_id = int(class_ids[best_index])
        confidence = float(confidences[best_index])
        label = result.names.get(class_id, str(class_id))
        return label, confidence

    return None, 0.0


def eye_aspect_ratio(points):
    a = np.linalg.norm(points[1] - points[5])
    b = np.linalg.norm(points[2] - points[4])
    c = np.linalg.norm(points[0] - points[3])
    return (a + b) / (2.0 * c + 1e-6)


def detect_mediapipe_eye_state(frame):
    if face_landmarker is None:
        return None

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_frame = mp_image.Image(image_format=mp_image.ImageFormat.SRGB, data=rgb_frame)
    frame_timestamp_ms = int(time.time() * 1000)
    results = face_landmarker.detect_for_video(mp_frame, frame_timestamp_ms)
    if not results.face_landmarks:
        return None

    face_landmarks = results.face_landmarks[0]
    frame_height, frame_width = frame.shape[:2]

    left_eye = np.array(
        [
            [face_landmarks[index].x * frame_width, face_landmarks[index].y * frame_height]
            for index in LEFT_EYE_LANDMARKS
        ],
        dtype=np.float32,
    )
    right_eye = np.array(
        [
            [face_landmarks[index].x * frame_width, face_landmarks[index].y * frame_height]
            for index in RIGHT_EYE_LANDMARKS
        ],
        dtype=np.float32,
    )

    left_ear = eye_aspect_ratio(left_eye)
    right_ear = eye_aspect_ratio(right_eye)
    ear = (left_ear + right_ear) / 2.0

    xs = [int(landmark.x * frame_width) for landmark in face_landmarks]
    ys = [int(landmark.y * frame_height) for landmark in face_landmarks]
    bbox = (max(min(xs), 0), max(min(ys), 0), min(max(xs) - min(xs), frame_width), min(max(ys) - min(ys), frame_height))

    return {
        "eye_closed": ear < MEDIAPIPE_EAR_THRESHOLD,
        "ear": ear,
        "bbox": bbox,
    }


def camera_stream():
    global video_frame, last_capture_time, last_frame_ts, closed_accum, current_user_id, esp32_alert_sent

    # If camera becomes unavailable during runtime, exit after repeated failures
    failed_read_count = 0
    MAX_FAILED_READS = int(10.0 / 0.05)  # ~10 seconds worth of failed reads at 50ms intervals

    while True:
        ret, frame = cap.read()
        if not ret:
            failed_read_count += 1
            if failed_read_count >= MAX_FAILED_READS:
                print(f"Error: Camera stopped returning frames for ~10s (failed {failed_read_count} reads). Exiting.")
                import sys
                sys.exit(1)
            time.sleep(0.05)
            continue
        else:
            failed_read_count = 0

        frame = cv2.resize(frame, (width, height))
        current_time = time.time()
        if last_frame_ts is None:
            dt = 0.033
        else:
            dt = current_time - last_frame_ts
        last_frame_ts = current_time

        eyes_detected = False
        show_warning = False

        if DETECTION_MODE == "mediapipe" and face_landmarker is not None:
            detection = detect_mediapipe_eye_state(frame)
            if detection is None:
                closed_accum = max(0.0, closed_accum - dt * 2.0)
                with lock:
                    video_frame = frame.copy()
                continue

            x, y, w, h = detection["bbox"]
            eye_closed = detection["eye_closed"]

            if eye_closed:
                closed_accum += dt
            else:
                closed_accum = max(0.0, closed_accum - dt * 2.0)

            if closed_accum >= EYE_CLOSED_DURATION_THRESHOLD:
                show_warning = True
                now_ts = time.time()
                if last_capture_time is None or (now_ts - last_capture_time) >= capture_interval:
                    last_capture_time = now_ts
                    filename = datetime.datetime.now().strftime("%H-%M-%S_%d-%m-%Y") + ".jpg"
                    filepath = os.path.join(capture_path, filename)
                    cv2.imwrite(filepath, frame)
                    print(f"Drowsiness detected! Image saved as {filepath}")
                    # Centralized alert: local beep + ESP32 + Arduino
                    trigger_alerts(filepath, alert_level="high")
                    esp32_alert_sent = True

                    # Blockchain event only if user logged in
                    if current_user_id:
                        blockchain.add_drowsiness_event(
                            user_id=current_user_id,
                            camera_id=CAMERA_URL,
                            image_path=filepath,
                            timestamp=datetime.datetime.now().isoformat(),
                            alert_level="high"
                        )
                        event_id = f"{current_user_id}_{now_ts}"
                        signature = user_manager.sign_event(event_id, filepath, current_user_id)
                        print(f"🔐 Chữ ký số được tạo: {signature[:16]}...")

            label_color = (0, 0, 255) if show_warning else ((0, 255, 255) if eye_closed else (0, 255, 0))
            cv2.putText(
                frame,
                f"MediaPipe EAR: {detection['ear']:.2f}",
                (x + 5, max(y - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                label_color,
                2,
            )
            cv2.rectangle(frame, (x, y), (x + w, y + h), label_color, 2)

            with lock:
                video_frame = frame.copy() if frame is not None else None
            # If warning cleared locally and we previously notified ESP32, send /alert/off
            if not show_warning and esp32_alert_sent:
                try:
                    if ESP32_ALERT_URL and esp32_available:
                        urllib.request.urlopen(f"{ESP32_ALERT_URL.rstrip('/')}/alert/off", timeout=2).read()
                        if DEBUG_LOG:
                            print(f"[ESP32] called {ESP32_ALERT_URL.rstrip('/')}/alert/off")
                except Exception as exc:
                    if DEBUG_LOG:
                        print(f"[ESP32] clear call failed: {exc}")
                esp32_alert_sent = False
            continue

        if DETECTION_MODE == "yolov8" and yolo_model is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            x = 0
            y = 0
            w = frame.shape[1]
            h = frame.shape[0]
            yolo_input = frame

            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
                yolo_input = frame[y:y+h, x:x+w]

            label, confidence = infer_yolo_label(yolo_input)
            if label is not None:
                normalized_label = label.strip().lower()
                eyes_detected = normalized_label in YOLO_DROWSY_LABELS

                if eyes_detected:
                    closed_accum += dt
                else:
                    closed_accum = max(0.0, closed_accum - dt * 2.0)

                if closed_accum >= EYE_CLOSED_DURATION_THRESHOLD:
                    show_warning = True
                    now_ts = time.time()
                    if last_capture_time is None or (now_ts - last_capture_time) > capture_interval:
                        last_capture_time = now_ts
                        filename = datetime.datetime.now().strftime("%H-%M-%S_%d-%m-%Y") + ".jpg"
                        filepath = os.path.join(capture_path, filename)
                        cv2.imwrite(filepath, frame)
                        print(f"Drowsiness detected! Image saved as {filepath}")
                        # Centralized alert handling
                        trigger_alerts(filepath, alert_level="high")
                        esp32_alert_sent = True

                        if current_user_id:
                            blockchain.add_drowsiness_event(
                                user_id=current_user_id,
                                camera_id=CAMERA_URL,
                                image_path=filepath,
                                timestamp=datetime.datetime.now().isoformat(),
                                alert_level="high"
                            )
                            event_id = f"{current_user_id}_{now_ts}"
                            signature = user_manager.sign_event(event_id, filepath, current_user_id)
                            print(f"🔐 Chữ ký số được tạo: {signature[:16]}...")

                color = (0, 0, 255) if show_warning else ((0, 255, 255) if eyes_detected else (0, 255, 0))
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, f"YOLOv8: {label} ({confidence:.2f})", (x + 5, max(y - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                with lock:
                    video_frame = frame.copy() if frame is not None else None
                # If warning cleared locally and we previously notified ESP32, send /alert/off
                if not show_warning and esp32_alert_sent:
                    try:
                        if ESP32_ALERT_URL and esp32_available:
                            urllib.request.urlopen(f"{ESP32_ALERT_URL.rstrip('/')}/alert/off", timeout=2).read()
                            if DEBUG_LOG:
                                print(f"[ESP32] called {ESP32_ALERT_URL.rstrip('/')}/alert/off")
                    except Exception as exc:
                        if DEBUG_LOG:
                            print(f"[ESP32] clear call failed: {exc}")
                    esp32_alert_sent = False
                continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        for (x, y, w, h) in faces:
            roi_gray = gray[y:y+h, x:x+w]
            roi_color = frame[y:y+h, x:x+w]
            eyes = eye_cascade.detectMultiScale(roi_gray)

            eye_closed = False
            if len(eyes) == 0:
                # Nếu không dò được mắt, có thể là mắt đang nhắm
                eyes_detected = True
                eye_closed = True
            else:
                for (ex, ey, ew, eh) in eyes:
                    eyes_detected = True
                    if eh < EYE_AR_THRESH:
                        eye_closed = True

            # Time-based detection with hysteresis accumulator
            now_ts = time.time()
            prev_ts = globals().get('last_frame_ts', None)
            if prev_ts is None:
                dt = 0.033
            else:
                dt = now_ts - prev_ts
            globals()['last_frame_ts'] = now_ts

            if DEBUG_LOG and eyes_detected:
                heights = [eh for (ex, ey, ew, eh) in eyes]
                print(f"[DEBUG] eyes={len(eyes)} heights={heights} closed={eye_closed} closed_accum={closed_accum:.2f}")

            # integrate closed time (decay when open)
            if eye_closed and eyes_detected:
                closed_accum += dt
            else:
                closed_accum = max(0.0, closed_accum - dt*2.0)

            if closed_accum >= EYE_CLOSED_DURATION_THRESHOLD:
                show_warning = True
                now_ts = time.time()
                if last_capture_time is None or (now_ts - last_capture_time) > capture_interval:
                    last_capture_time = now_ts
                    filename = datetime.datetime.now().strftime("%H-%M-%S_%d-%m-%Y") + ".jpg"
                    filepath = os.path.join(capture_path, filename)
                    cv2.imwrite(filepath, frame)
                    print(f"Drowsiness detected! Image saved as {filepath}")
                    # Centralized alert handling
                    trigger_alerts(filepath, alert_level="high")
                    esp32_alert_sent = True

                    # === BLOCKCHAIN: Ghi sự kiện buồn ngủ ===
                    if current_user_id:
                        blockchain.add_drowsiness_event(
                            user_id=current_user_id,
                            camera_id=CAMERA_URL,
                            image_path=filepath,
                            timestamp=datetime.datetime.now().isoformat(),
                            alert_level="high"
                        )
                        # Tạo chữ ký số cho sự kiện
                        event_id = f"{current_user_id}_{now_ts}"
                        signature = user_manager.sign_event(event_id, filepath, current_user_id)
                        print(f"🔐 Chữ ký số được tạo: {signature[:16]}...")

            # Draw rectangles for detected eyes
            for (ex, ey, ew, eh) in eyes:
                color = (0, 255, 0)  # green default
                if show_warning:
                    color = (0, 0, 255)  # red when warning
                elif eye_closed:
                    color = (0, 255, 255)  # yellow when temporarily closed
                cv2.rectangle(roi_color, (ex, ey), (ex+ew, ey+eh), color, 2)
            # If warning, add overlay text
            if show_warning:
                cv2.putText(frame, "CẢNH BÁO: NGỦ GẬT", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
        with lock:
            video_frame = frame.copy() if frame is not None else None
        # If warning cleared locally and we previously notified ESP32, send /alert/off
        if not show_warning and esp32_alert_sent:
            try:
                if ESP32_ALERT_URL and esp32_available:
                    urllib.request.urlopen(f"{ESP32_ALERT_URL.rstrip('/')}/alert/off", timeout=2).read()
                    if DEBUG_LOG:
                        print(f"[ESP32] called {ESP32_ALERT_URL.rstrip('/')}/alert/off")
            except Exception as exc:
                if DEBUG_LOG:
                    print(f"[ESP32] clear call failed: {exc}")
            esp32_alert_sent = False


def gen_frames():
    global video_frame
    while True:
        with lock:
            if video_frame is None:
                time.sleep(0.1)
                continue
            ret, buffer = cv2.imencode('.jpg', video_frame)
            if not ret:
                continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/camera/select', methods=['POST'])
def select_camera():
    """Switch active camera by local index (JSON: {"index": 0})"""
    global cap, is_http_reader, CAMERA_URL
    data = request.get_json(force=True, silent=True) or {}
    if 'index' not in data:
        return jsonify({'success': False, 'message': 'Missing index'}), 400
    try:
        idx = int(data.get('index'))
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid index'}), 400

    # Persist selection for subsequent opens
    os.environ['CAMERA_INDEX'] = str(idx)

    # Release existing capture/reader
    try:
        if is_http_reader and hasattr(cap, 'release'):
            cap.release()
        elif hasattr(cap, 'isOpened') and cap.isOpened():
            cap.release()
    except Exception:
        pass

    # Recreate stream (will prefer local CAMERA_INDEX)
    try:
        cap, is_http_reader = create_camera_stream(CAMERA_URL, use_http_reader=True, width=320, height=240)
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Failed to open camera: {exc}'}), 500

    opened = cap.is_opened() if is_http_reader else getattr(cap, 'isOpened', lambda: False)()
    return jsonify({'success': True, 'camera_index': idx, 'is_opened': bool(opened)}), 200


@app.route('/api/camera/status', methods=['GET'])
def camera_status():
    """Return the current camera and ESP32 state for the dashboard."""
    opened = cap.is_opened() if is_http_reader else getattr(cap, 'isOpened', lambda: False)()
    backend = 'http_reader' if is_http_reader else 'cv2_capture'
    camera_index_env = os.environ.get('CAMERA_INDEX', '').strip()
    camera_url_env = os.environ.get('CAMERA_URL', CAMERA_URL).strip()

    esp32_status = None
    if ESP32_ALERT_URL:
        ok, data = fetch_remote_json(f"{ESP32_ALERT_URL}/status", timeout=2)
        esp32_status = data if ok else {'error': data}

    return jsonify({
        'success': True,
        'camera': {
            'url': camera_url_env,
            'index': camera_index_env,
            'backend': backend,
            'opened': bool(opened),
            'detection_mode': DETECTION_MODE,
        },
        'esp32': {
            'url': ESP32_ALERT_URL or None,
            'status': esp32_status,
        },
    }), 200


@app.route('/api/vehicle/control', methods=['POST'])
def vehicle_control():
    """Proxy start/stop/status to the ESP32 motor controller."""
    data = request.get_json(force=True, silent=True) or {}
    action = str(data.get('action', '')).strip().lower()
    if not ESP32_ALERT_URL:
        return jsonify({'success': False, 'message': 'ESP32_ALERT_URL is not configured'}), 400

    endpoint_map = {
        'stop': '/vehicle/stop',
        'start': '/vehicle/start',
        'status': '/status',
    }
    if action not in endpoint_map:
        return jsonify({'success': False, 'message': 'action must be start, stop, or status'}), 400

    ok, data = fetch_remote_json(f"{ESP32_ALERT_URL}{endpoint_map[action]}", timeout=2)
    if not ok:
        return jsonify({'success': False, 'message': data}), 502
    return jsonify({'success': True, 'action': action, 'esp32': data}), 200


@app.route('/')
def index():
    return render_template('index_flask_server.html')


@app.route('/dashboard')
def dashboard():
    """Giao diện dashboard blockchain"""
    return render_template('auth_dashboard.html')


@app.route('/ui/manager')
@require_login
def ui_manager():
    """Manager / Supervisor dashboard UI"""
    user_info = user_manager.get_user_info(current_user_id) if current_user_id else None
    return render_template('manager_dashboard.html', user=user_info)


@app.route('/ui/admin')
@require_role('admin')
def ui_admin():
    """Admin dashboard UI"""
    user_info = user_manager.get_user_info(current_user_id) if current_user_id else None
    return render_template('admin_dashboard.html', user=user_info)


@app.route('/api/images/list', methods=['GET'])
@require_login
def api_images_list():
    """Return recent captured images (filenames and timestamps)"""
    files = []
    try:
        for fn in sorted(os.listdir(capture_path), reverse=True):
            if fn.lower().endswith('.jpg'):
                full = os.path.join(capture_path, fn)
                ts = os.path.getmtime(full)
                files.append({'filename': fn, 'path': f'/captures/{fn}', 'ts': ts})
    except Exception:
        pass
    return jsonify({'success': True, 'images': files}), 200


@app.route('/captures/<path:filename>')
@require_login
def serve_capture(filename):
    # Simple static file serving for captured images
    safe_fname = os.path.basename(filename)
    return send_from_directory(capture_path, safe_fname)


@app.route('/api/admin/users', methods=['GET'])
@require_role('admin')
def api_admin_list_users():
    users = user_manager.list_users()
    return jsonify({'success': True, 'users': users}), 200


@app.route('/api/admin/users/<user_id>/role', methods=['POST'])
@require_role('admin')
def api_admin_set_role(user_id):
    data = request.get_json(force=True, silent=True) or {}
    role = data.get('role')
    if not role:
        return jsonify({'success': False, 'message': 'Missing role'}), 400
    ok = user_manager.set_user_role(user_id, role)
    if not ok:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    return jsonify({'success': True, 'user_id': user_id, 'role': role}), 200


# ============ BLOCKCHAIN ROUTES ============

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Đăng ký người dùng mới"""
    global current_user_id
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    if not all([username, email, password]):
        return jsonify({'success': False, 'message': 'Thiếu thông tin đăng ký'}), 400
    success, result = user_manager.register_user(username, email, password)
    if success:
        current_user_id = result
        user_manager.log_access(result, 'register', 'system', 'success')
        blockchain.add_access_log(result, 'user_registered', 'system')
        token = user_manager.create_session(result)
        return jsonify({
            'success': True,
            'message': 'Đăng ký thành công',
            'user_id': result,
            'token': token
        }), 201
    else:
        return jsonify({'success': False, 'message': result}), 400


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Đăng nhập"""
    global current_user_id, current_user_token
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Thiếu username hoặc password'}), 400
    success, user_id = user_manager.authenticate_user(username, password)
    if success:
        current_user_id = user_id
        token = user_manager.create_session(user_id)
        current_user_token = token
        user_manager.log_access(user_id, 'login', 'system', 'success')
        blockchain.add_access_log(user_id, 'user_login', 'system')
        # create browser session for form-based UI
        session['user_id'] = user_id
        session['username'] = username
        return jsonify({
            'success': True,
            'message': 'Đăng nhập thành công',
            'user_id': user_id,
            'token': token
        }), 200
    else:
        return jsonify({'success': False, 'message': user_id}), 401


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Đăng xuất"""
    global current_user_id, current_user_token
    if current_user_id:
        user_manager.log_access(current_user_id, 'logout', 'system', 'success')
        blockchain.add_access_log(current_user_id, 'user_logout', 'system')
        current_user_id = None
        current_user_token = None
    return jsonify({'success': True, 'message': 'Đã đăng xuất'}), 200


@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    """Lấy thông tin người dùng hiện tại"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    user_info = user_manager.get_user_info(current_user_id)
    if user_info:
        user_manager.log_access(current_user_id, 'view_profile', 'user_info', 'success')
        return jsonify({'success': True, 'user': user_info}), 200
    else:
        return jsonify({'success': False, 'message': 'Không tìm thấy người dùng'}), 404


@app.route('/api/events/drowsiness', methods=['GET'])
def get_drowsiness_events():
    """Lấy danh sách các sự kiện phát hiện buồn ngủ"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    days = request.args.get('days', default=None, type=int)
    user_manager.log_access(current_user_id, 'view_events', 'drowsiness_events', 'success')
    events = blockchain.get_drowsiness_events(current_user_id, days)
    return jsonify({
        'success': True,
        'total_events': len(events),
        'events': events
    }), 200


@app.route('/api/user/history', methods=['GET'])
def get_user_history():
    """Lấy toàn bộ lịch sử của người dùng từ blockchain (Kiểm toán)"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    user_manager.log_access(current_user_id, 'view_history', 'blockchain_history', 'success')
    history = blockchain.get_user_history(current_user_id)
    return jsonify({
        'success': True,
        'total_records': len(history),
        'history': history
    }), 200


@app.route('/api/blockchain/status', methods=['GET'])
def blockchain_status():
    """Lấy trạng thái blockchain"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    user_manager.log_access(current_user_id, 'view_status', 'blockchain_status', 'success')
    return jsonify({
        'success': True,
        'total_blocks': len(blockchain.chain),
        'pending_transactions': len(blockchain.pending_transactions),
        'is_valid': blockchain.is_chain_valid(),
        'latest_block_hash': blockchain.get_latest_block().hash[:16] + '...'
    }), 200


@app.route('/api/blockchain/mine', methods=['POST'])
def mine_blockchain():
    """Khai thác một khối mới (Admin only)"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    if len(blockchain.pending_transactions) == 0:
        return jsonify({'success': False, 'message': 'Không có giao dịch để khai thác'}), 400
    success = blockchain.mine_pending_transactions(current_user_id)
    blockchain.add_audit_log('blockchain_mined', {'blocks_mined': 1}, current_user_id)
    if success:
        return jsonify({
            'success': True,
            'message': 'Khối được khai thác thành công',
            'block_hash': blockchain.get_latest_block().hash[:16] + '...'
        }), 200
    else:
        return jsonify({'success': False, 'message': 'Lỗi khi khai thác'}), 500


@app.route('/api/blockchain/export', methods=['GET'])
def export_blockchain():
    """Xuất toàn bộ blockchain (CSV format cho báo cáo)"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    user_manager.log_access(current_user_id, 'export_blockchain', 'blockchain_data', 'success')
    blockchain.add_audit_log('blockchain_exported', {'user': current_user_id}, 'system')
    chain_data = blockchain.export_chain()
    return jsonify({
        'success': True,
        'blockchain': chain_data
    }), 200


@app.route('/api/blockchain/verify', methods=['GET'])
def verify_blockchain():
    """Xác minh tính toàn vẹn của blockchain"""
    if not current_user_id:
        return jsonify({'success': False, 'message': 'Chưa đăng nhập'}), 401
    is_valid = blockchain.is_chain_valid()
    blockchain.add_audit_log('blockchain_verified', {'is_valid': is_valid}, current_user_id)
    return jsonify({
        'success': True,
        'is_valid': is_valid,
        'total_blocks': len(blockchain.chain)
    }), 200


def run_server():
    """Start camera thread, background miners, and run the Flask app.
    Call this from start_app.py or when running importcv2.py directly.
    """
    # Thread chính: stream camera
    camera_thread = Thread(target=camera_stream, daemon=True)
    camera_thread.start()

    # Thread định kỳ: khai thác blockchain mỗi 5 phút
    def periodic_mining():
        while True:
            time.sleep(300)  # 5 phút
            if len(blockchain.pending_transactions) > 0 and current_user_id:
                print("🔨 Đang khai thác blockchain định kỳ...")
                blockchain.mine_pending_transactions("system")

    mining_thread = Thread(target=periodic_mining, daemon=True)
    mining_thread.start()

    try:
        print("\n" + "="*60)
        print("🚀 Hệ thống phát hiện buồn ngủ với Blockchain đã khởi động")
        print("="*60)
        print("📍 Truy cập tại: http://localhost:5000")
        print("🔗 API Blockchain:")
        print("   - POST /api/auth/register - Đăng ký")
        print("   - POST /api/auth/login - Đăng nhập")
        print("   - GET  /api/events/drowsiness - Xem sự kiện")
        print("   - GET  /api/blockchain/status - Trạng thái blockchain")
        print("="*60 + "\n")
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    finally:
        try:
            if is_http_reader and hasattr(cap, 'release'):
                cap.release()
            elif hasattr(cap, 'isOpened') and cap.isOpened():
                cap.release()
        except Exception:
            pass


if __name__ == '__main__':
    run_server()
