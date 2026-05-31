from flask import Flask, render_template, Response, jsonify, request, session, redirect, url_for, send_from_directory, has_request_context
import json
import cv2
import numpy as np
import time
import datetime
import os
import secrets
from collections import deque
from threading import Thread, Lock
from playsound import playsound
import platform
from gtts import gTTS
import tempfile
import pygame
import threading
import sys
import urllib.request
from PIL import ImageFont, ImageDraw, Image

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use environment variables directly

# Import Blockchain & Identity Management
from blockchain import DrowsinessBlockchain
from user_identity import UserIdentityManager

# Import Web3 for Ethereum integration
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from mediapipe.tasks.python.core import base_options as mp_base_options
    from mediapipe.tasks.python.vision import face_landmarker as mp_face_landmarker
    from mediapipe.tasks.python.vision.core import image as mp_image
    from mediapipe.tasks.python.vision.core import vision_task_running_mode as mp_running_mode
except ImportError:
    mp_base_options = None
    mp_face_landmarker = None
    mp_image = None
    mp_running_mode = None

if platform.system() == "Windows":
    import winsound

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_urlsafe(32))
SYSTEM_NAME = 'Smart Traffic Safety'

# Khởi tạo Blockchain và User Manager
blockchain = DrowsinessBlockchain(difficulty=1)
user_manager = UserIdentityManager()
pending_metamask_alerts = deque()
pending_metamask_lock = Lock()

# Khởi tạo Web3 cho Ethereum
# Sử dụng environment variables hoặc defaults
INFURA_URL = os.environ.get('INFURA_URL', "https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID")
CONTRACT_ADDRESS = os.environ.get('CONTRACT_ADDRESS', "0xYourContractAddress")
PRIVATE_KEY = os.environ.get('PRIVATE_KEY', "0xYourPrivateKey")

web3 = Web3(Web3.HTTPProvider(INFURA_URL))
web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "_userId", "type": "string"},
            {"internalType": "string", "name": "_cameraId", "type": "string"},
            {"internalType": "string", "name": "_imagePath", "type": "string"},
            {"internalType": "string", "name": "_timestamp", "type": "string"},
            {"internalType": "string", "name": "_alertLevel", "type": "string"}
        ],
        "name": "addDrowsinessEvent",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getEventCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Safely create contract object. If CONTRACT_ADDRESS is not a valid hex address
# (e.g. placeholder like "0xYourContractAddress"), avoid ENS resolution errors
# by creating a contract factory without an address.
try:
    if CONTRACT_ADDRESS and Web3.is_address(CONTRACT_ADDRESS):
        try:
            CONTRACT_ADDRESS = Web3.to_checksum_address(CONTRACT_ADDRESS)
        except Exception:
            # to_checksum_address may fail on invalid inputs; continue and let
            # web3 handle or fallback below
            pass
        contract = web3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)
    else:
        print(f"⚠ CONTRACT_ADDRESS not set or invalid: {CONTRACT_ADDRESS!r}. Using contract factory without address.")
        contract = web3.eth.contract(abi=CONTRACT_ABI)
except AttributeError as e:
    # This can happen when ENS is empty and tries to resolve a non-address string.
    print(f"⚠ ENS/address error creating contract: {e}. Creating contract factory without address.")
    contract = web3.eth.contract(abi=CONTRACT_ABI)
except Exception as e:
    print(f"⚠ Unexpected error creating contract: {e}. Creating contract factory without address.")
    contract = web3.eth.contract(abi=CONTRACT_ABI)

# Private key cho MetaMask (chỉ dùng cho demo, không dùng trong production)
PRIVATE_KEY = "0xYourPrivateKey"  # Thay bằng private key từ MetaMask

# Tạo sẵn một vài tài khoản mẫu
if len(user_manager.users) == 0:
    user_manager.register_user('driver1', 'driver1@example.com', '123456')
    user_manager.register_user('driver2', 'driver2@example.com', '123456')

# Global session state (cho thread camera)
active_user_id = None
user_id = "USER_001"  # ID người dùng/tài xế mặc định
camera_id = "CAMERA_001"  # ID camera

# Use environment variable `CAMERA_URL` if provided
stream_url = os.environ.get('CAMERA_URL', 'http://172.16.7.189:4747/video/')
use_ffmpeg = os.environ.get('USE_FFMPEG', '1') == '1'
print(f"🔍 Attempting camera stream: {stream_url} (USE_FFMPEG={use_ffmpeg})")

try:
    if stream_url.startswith('http') and use_ffmpeg:
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        backend_used = 'CAP_FFMPEG'
    else:
        # Let OpenCV choose a sensible backend for non-HTTP or when ffmpeg disabled
        cap = cv2.VideoCapture(stream_url)
        backend_used = 'default'
except Exception as e:
    print(f"⚠ Exception opening stream {stream_url}: {e}")
    cap = cv2.VideoCapture(0)
    backend_used = 'fallback'

cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
print(f"📡 Opened stream with backend={backend_used}, cap.isOpened()={cap.isOpened()}")

# Thử kết nối camera: nếu URL không hoạt động, fallback sang webcam cục bộ
valid_stream = False
for _ in range(10):
    try:
        ret, _ = cap.read()
    except Exception:
        ret = False
    if ret:
        valid_stream = True
        break
    time.sleep(0.1)

if not valid_stream or not cap.isOpened():
    print(f"⚠ Không thể kết nối {stream_url}, đang chuyển sang webcam cục bộ...")
    try:
        cap.release()
    except Exception:
        pass

    # Try to find a working local camera index. Honor LOCAL_CAMERA_INDEX if set.
    preferred = []
    env_idx = os.environ.get('LOCAL_CAMERA_INDEX')
    if env_idx and env_idx.isdigit():
        preferred.append(int(env_idx))
    preferred += list(range(0, 6))

    found = False
    for idx in preferred:
        try:
            if platform.system() == 'Windows':
                c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            else:
                c = cv2.VideoCapture(idx)
            c.set(cv2.CAP_PROP_BUFFERSIZE, 2)
            ret, _ = c.read()
            if ret and c.isOpened():
                cap = c
                print(f"✅ Found local webcam index={idx}, cap.isOpened()={cap.isOpened()}")
                found = True
                break
            else:
                try:
                    c.release()
                except Exception:
                    pass
        except Exception:
            try:
                c.release()
            except Exception:
                pass

    if not found:
        print("⚠ Không tìm thấy webcam cục bộ; tiếp tục với cap hiện tại (mất kết nối)")

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

fps = 25
width, height = 320, 240
video_frame = None
lock = Lock()
capture_path = "captured_images"
os.makedirs(capture_path, exist_ok=True)

EYE_CLOSED_DURATION_THRESHOLD = 2.0
EYE_PIXEL_THRESHOLD = 12
closed_accum = 0.0
last_frame_ts = None
last_capture_time = None
capture_interval = 5.0

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

LEFT_EYE_LANDMARKS = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_LANDMARKS = [362, 385, 387, 263, 373, 380]

yolo_model = None
if DETECTION_MODE == "yolov8":
    if YOLO is None:
        print("⚠ ultralytics chưa được cài, chuyển sang chế độ Haar cascade.")
        DETECTION_MODE = "haar"
    else:
        try:
            yolo_model = YOLO(YOLO_MODEL_PATH)
            print(f"✅ Đã nạp YOLOv8 model: {YOLO_MODEL_PATH}")
        except Exception as exc:
            print(f"⚠ Không nạp được YOLOv8 model {YOLO_MODEL_PATH!r}: {exc}")
            print("⚠ Chuyển sang chế độ Haar cascade.")
            DETECTION_MODE = "haar"

face_landmarker = None
if DETECTION_MODE == "mediapipe":
    if mp_face_landmarker is None or mp_base_options is None or mp_image is None or mp_running_mode is None:
        print("⚠ MediaPipe Tasks API chưa khả dụng, chuyển sang chế độ Haar cascade.")
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
            print("✅ Đã nạp MediaPipe Face Landmarker.")
        except Exception as exc:
            print(f"⚠ Không nạp được MediaPipe Face Landmarker: {exc}")
            print("⚠ Chuyển sang chế độ Haar cascade.")
            DETECTION_MODE = "haar"

alert_audio = "alarm.mp3"

# Font hỗ trợ tiếng Việt
if platform.system() == "Windows":
    FONT_PATH = "C:\\Windows\\Fonts\\arial.ttf"
else:
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

alert_playing = False
last_alert_time = 0
ALERT_COOLDOWN = 5  

pygame.mixer.init()

def play_alert_sound():
    global alert_playing, last_alert_time
    if time.time() - last_alert_time < ALERT_COOLDOWN:
        return  
    last_alert_time = time.time()
    try:
        if os.path.exists(alert_audio):
            playsound(alert_audio)
        else:
            print("⚠ Không tìm thấy file âm thanh, phát beep thay thế.")
            if platform.system() == "Windows":
                winsound.Beep(1000, 500)
    except Exception as e:
        print("Lỗi khi phát âm thanh cảnh báo:", e)
    finally:
        alert_playing = False

def sendWarning(text):
    global alert_playing, last_alert_time
    if alert_playing or (time.time() - last_alert_time < ALERT_COOLDOWN):
        return  
    alert_playing = True
    
    def play_audio():
        global alert_playing
        temp_audio_path = None
        try:
            tts = gTTS(text=text, lang="vi")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_audio_file:
                temp_audio_path = temp_audio_file.name
            tts.save(temp_audio_path)
            pygame.mixer.music.load(temp_audio_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
        except Exception as e:
            print(f"Lỗi âm thanh: {e}", file=sys.stderr)
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass
        finally:
            alert_playing = False
    
    threading.Thread(target=play_audio, daemon=True).start()

def get_current_user_id():
    if has_request_context():
        return session.get('user_id') or active_user_id or user_id
    return active_user_id or user_id


def get_current_username():
    uid = session.get('user_id') or active_user_id
    if not uid:
        return 'Mặc định'
    info = user_manager.get_user_info(uid)
    return info['username'] if info else uid


def capture_image(frame):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(capture_path, f"alert_{timestamp}.jpg")
    cv2.imwrite(filename, frame)
    print(f"📸 Ảnh đã được lưu: {filename}")
    
    # Ghi sự kiện phát hiện buồn ngủ vào blockchain
    active = get_current_user_id()
    blockchain.add_drowsiness_event(
        user_id=active,
        camera_id=camera_id,
        image_path=filename,
        timestamp=timestamp,
        alert_level="high"
    )

    # Đưa vào hàng đợi để frontend tự gửi qua MetaMask
    alert_event = {
        "alert_id": f"{active}_{timestamp}",
        "user_id": active,
        "camera_id": camera_id,
        "image_path": filename,
        "timestamp": timestamp,
        "alert_level": "high"
    }
    with pending_metamask_lock:
        pending_metamask_alerts.append(alert_event)
    print(f"🦊 Đã xếp hàng sự kiện để gửi qua MetaMask: {alert_event['alert_id']}")
    
    # Tạo chữ ký số cho sự kiện
    event_id = f"{active}_{timestamp}"
    signature = user_manager.sign_event(event_id, filename, active)
    print(f"🔐 Chữ ký số được tạo: {signature[:16]}...")
    
    # Ghi log truy cập
    blockchain.add_access_log(active, 'drowsiness_detected', 'camera_feed', 'alert')

def reconnect_camera():
    global cap
    try:
        cap.release()
    except Exception:
        pass
    time.sleep(1)

    # Try reopening the configured stream first (use FFmpeg if enabled)
    try:
        if stream_url.startswith('http') and use_ffmpeg:
            cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
            backend = 'CAP_FFMPEG'
        else:
            cap = cv2.VideoCapture(stream_url)
            backend = 'default'
    except Exception as e:
        print(f"⚠ reconnect_camera: exception opening stream: {e}")
        backend = 'exception'
        if platform.system() == 'Windows':
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(0)

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

    # Kiểm tra kết nối
    valid = False
    for _ in range(5):
        try:
            ret, _ = cap.read()
        except Exception:
            ret = False
        if ret:
            valid = True
            break
        time.sleep(0.1)

    if not valid:
        print("Fallback sang webcam cục bộ...")
        try:
            cap.release()
        except Exception:
            pass

        # Try several local camera indices on reconnect
        preferred = []
        env_idx = os.environ.get('LOCAL_CAMERA_INDEX')
        if env_idx and env_idx.isdigit():
            preferred.append(int(env_idx))
        preferred += list(range(0, 6))

        found = False
        for idx in preferred:
            try:
                if platform.system() == 'Windows':
                    c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                else:
                    c = cv2.VideoCapture(idx)
                c.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                ret, _ = c.read()
                if ret and c.isOpened():
                    cap = c
                    print(f"✅ Reconnected local webcam index={idx}")
                    found = True
                    break
                else:
                    try:
                        c.release()
                    except Exception:
                        pass
            except Exception:
                try:
                    c.release()
                except Exception:
                    pass

        if not found:
            print("⚠ Không tìm thấy webcam cục bộ trên các index thử nghiệm")

def mine_blockchain():
    """Hàm khai thác blockchain giao dịch đã lưu vào từng 30 giây"""
    while True:
        time.sleep(30)  # Khai thác mỗi 30 giây
        if len(blockchain.pending_transactions) > 0:
            print(f"\n⛏️  Đang khai thác blockchain ({len(blockchain.pending_transactions)} giao dịch)...")
            blockchain.mine_pending_transactions(miner_id="SERVER_001")
            print(f"✅ Blockchain được cập nhật! Tổng khối: {len(blockchain.chain)}\n")


@app.route('/api/metamask/next-alert', methods=['GET'])
def api_metamask_next_alert():
    """Lấy cảnh báo tiếp theo đang chờ gửi lên MetaMask"""
    with pending_metamask_lock:
        if not pending_metamask_alerts:
            return jsonify({'has_alert': False}), 200
        return jsonify({'has_alert': True, 'alert': pending_metamask_alerts[0]}), 200


@app.route('/api/metamask/ack-alert', methods=['POST'])
def api_metamask_ack_alert():
    """Xác nhận một cảnh báo đã được gửi thành công qua MetaMask"""
    data = request.get_json(silent=True) or {}
    alert_id = data.get('alert_id')
    if not alert_id:
        return jsonify({'success': False, 'message': 'Thiếu alert_id'}), 400

    with pending_metamask_lock:
        for index, alert in enumerate(list(pending_metamask_alerts)):
            if alert.get('alert_id') == alert_id:
                pending_metamask_alerts.remove(alert)
                return jsonify({'success': True, 'message': 'Đã xác nhận alert'}), 200

    return jsonify({'success': False, 'message': 'Không tìm thấy alert'}), 404

def draw_text_vietnamese(img, text, position, color=(0, 255, 0), font_size=16):
    """Hàm vẽ chữ hỗ trợ tiếng Việt với kích thước font có thể thay đổi."""
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = ImageFont.truetype(FONT_PATH, font_size)  # 🔥 Thêm font_size vào đây
    draw.text(position, text, font=font, fill=color)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def infer_yolo_label(frame):
    if yolo_model is None:
        return None, 0.0

    try:
        result = yolo_model.predict(frame, imgsz=YOLO_IMAGE_SIZE, verbose=False)[0]
    except Exception as exc:
        print(f"⚠ Lỗi suy luận YOLOv8: {exc}")
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
        [[face_landmarks[index].x * frame_width, face_landmarks[index].y * frame_height] for index in LEFT_EYE_LANDMARKS],
        dtype=np.float32,
    )
    right_eye = np.array(
        [[face_landmarks[index].x * frame_width, face_landmarks[index].y * frame_height] for index in RIGHT_EYE_LANDMARKS],
        dtype=np.float32,
    )

    left_ear = eye_aspect_ratio(left_eye)
    right_ear = eye_aspect_ratio(right_eye)
    ear = (left_ear + right_ear) / 2.0

    xs = [int(landmark.x * frame_width) for landmark in face_landmarks]
    ys = [int(landmark.y * frame_height) for landmark in face_landmarks]
    x_min = max(min(xs), 0)
    y_min = max(min(ys), 0)
    x_max = min(max(xs), frame_width)
    y_max = min(max(ys), frame_height)

    return {
        "eye_closed": ear < MEDIAPIPE_EAR_THRESHOLD,
        "ear": ear,
        "bbox": (x_min, y_min, max(x_max - x_min, 1), max(y_max - y_min, 1)),
    }

@app.route('/login', methods=['GET', 'POST'])
def login():
    message = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            message = 'Vui lòng nhập đầy đủ username và password.'
        else:
            success, user_or_error = user_manager.authenticate_user(username, password)
            if success:
                session['user_id'] = user_or_error
                session['username'] = username
                global active_user_id
                active_user_id = user_or_error
                user_manager.log_access(user_or_error, 'login', 'system', 'success')
                blockchain.add_access_log(user_or_error, 'user_login', 'system')
                # redirect based on selected role from form (default to driver/home)
                selected_role = request.form.get('role', 'driver')
                if selected_role == 'manager':
                    return redirect(url_for('ui_manager'))
                if selected_role == 'admin':
                    return redirect(url_for('ui_admin'))
                return redirect(url_for('index'))
            else:
                message = user_or_error
    return render_template('auth_login.html', message=message)


@app.route('/ui/manager')
def ui_manager():
    # session-based access for manager/supervisor
    uid = session.get('user_id')
    if not uid:
        return redirect(url_for('login'))
    raw = user_manager.get_raw_user(uid)
    user_role = raw.get('role', 'driver') if raw else 'driver'
    if user_role not in ('manager', 'admin'):
        return "Không đủ quyền truy cập", 403
    user_info = user_manager.get_user_info(uid) if uid else None
    return render_template('manager_dashboard.html', user=user_info)


@app.route('/ui/admin')
def ui_admin():
    # session-based access for admin only
    uid = session.get('user_id')
    if not uid:
        return redirect(url_for('login'))
    raw = user_manager.get_raw_user(uid)
    user_role = raw.get('role', 'driver') if raw else 'driver'
    if user_role != 'admin':
        return "Không đủ quyền truy cập", 403
    user_info = user_manager.get_user_info(uid) if uid else None
    return render_template('admin_dashboard.html', user=user_info)


@app.route('/logout')
def logout():
    user = session.pop('user_id', None)
    session.pop('username', None)
    if user:
        user_manager.log_access(user, 'logout', 'system', 'success')
        blockchain.add_access_log(user, 'user_logout', 'system')
    return redirect(url_for('login'))


@app.route('/captured_images/<path:filename>')
def captured_image(filename):
    return send_from_directory(capture_path, filename)


def camera_stream():

    global video_frame, closed_accum, last_frame_ts, last_capture_time
    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠ Mất kết nối camera, đang thử kết nối lại...")
            reconnect_camera()
            time.sleep(0.5)
            continue

        frame = cv2.resize(frame, (width, height))

        current_time = time.time()
        if last_frame_ts is None:
            dt = 0.033
        else:
            dt = current_time - last_frame_ts
        last_frame_ts = current_time

        eye_closed = False
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
                    sendWarning("Cảnh báo Smart Traffic Safety: tài xế có dấu hiệu buồn ngủ, hãy dừng xe và nghỉ ngơi.")
                    capture_image(frame)

            label_color = (0, 0, 255) if show_warning else ((0, 255, 255) if eye_closed else (0, 255, 0))
            frame = draw_text_vietnamese(frame, f"MediaPipe EAR: {detection['ear']:.2f}", (x + 5, max(y - 10, 20)), label_color)
            cv2.rectangle(frame, (x, y), (x + w, y + h), label_color, 2)

            with lock:
                video_frame = frame.copy()
            continue

        if DETECTION_MODE == "yolov8" and yolo_model is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)
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
                eye_closed = normalized_label in YOLO_DROWSY_LABELS

                if eye_closed:
                    closed_accum += dt
                else:
                    closed_accum = max(0.0, closed_accum - dt * 2.0)

                if closed_accum >= EYE_CLOSED_DURATION_THRESHOLD:
                    show_warning = True

                label_color = (0, 0, 255) if show_warning else ((0, 255, 255) if eye_closed else (0, 255, 0))
                frame = draw_text_vietnamese(frame, f"YOLOv8: {label} ({confidence:.2f})", (x + 5, max(y - 10, 10)), label_color)
                cv2.rectangle(frame, (x, y), (x + w, y + h), label_color, 2)

                if show_warning:
                    if last_capture_time is None or (current_time - last_capture_time) >= capture_interval:
                        last_capture_time = current_time
                        sendWarning("Cảnh báo Smart Traffic Safety: tài xế có dấu hiệu buồn ngủ, hãy dừng xe và nghỉ ngơi.")
                        capture_image(frame)

                with lock:
                    video_frame = frame.copy()
                continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

        if len(faces) == 0:
            closed_accum = max(0.0, closed_accum - dt * 2.0)
            with lock:
                video_frame = frame.copy()
            continue

        for (x, y, w, h) in faces:
            roi_gray = gray[y:y+h, x:x+w]
            roi_color = frame[y:y+h, x:x+w]

            # 📌 **Phát hiện mắt**
            eyes = eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=5)
            eyes_detected = len(eyes) > 0

            closed_count = 0  # Đếm số mắt nhắm
            for (ex, ey, ew, eh) in eyes:
                if eh < EYE_PIXEL_THRESHOLD:
                    closed_count += 1

            # Nếu không tìm được mắt, có thể đang nhắm
            if not eyes_detected:
                eye_closed = True
            else:
                eye_closed = closed_count > 0

            if eye_closed:
                closed_accum += dt
            else:
                closed_accum = max(0.0, closed_accum - dt * 2.0)

            if closed_accum >= EYE_CLOSED_DURATION_THRESHOLD:
                show_warning = True

            # 📌 **Vẽ khung mắt dựa vào trạng thái**
            for (ex, ey, ew, eh) in eyes:
                eye_x, eye_y, eye_w, eye_h = x + ex, y + ey, ew, eh
                
                if show_warning:
                    color = (0, 0, 255)  # 🔴 **Mắt nhắm ≥ 2s → Khung đỏ**
                elif eye_closed:
                    color = (0, 255, 255)  # 🟡 **Mắt nhắm - tạm thời**
                else:
                    color = (0, 255, 0)  # ✅ **Mắt mở**
                
                cv2.rectangle(frame, (eye_x, eye_y), (eye_x + eye_w, eye_y + eye_h), color, 2)

            # 📌 **Vẽ khung mặt và cảnh báo**
            if show_warning:  # 🔴 **Mắt nhắm quá 2s → Cảnh báo**
                if last_capture_time is None or (current_time - last_capture_time) >= capture_interval:
                    last_capture_time = current_time
                    frame = draw_text_vietnamese(frame, "SMART TRAFFIC SAFETY", (x + 5, y - 10), (255, 0, 0))  # 🟥 Chữ đỏ
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)  # 🟥 Khung mặt đỏ
                    sendWarning("Cảnh báo Smart Traffic Safety: tài xế có dấu hiệu buồn ngủ, hãy dừng xe và nghỉ ngơi.")
                    capture_image(frame)
                else:
                    frame = draw_text_vietnamese(frame, "SMART TRAFFIC SAFETY", (x + 5, y - 10), (255, 0, 0))
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
            elif eye_closed:  # 🟡 **Mắt nhắm nhưng chưa quá 2s**
                frame = draw_text_vietnamese(frame, "Mắt nhắm - Cần chú ý", (x + 5, y - 10), (255, 255, 0))  # 🟡 Chữ vàng
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)  # 🟡 Khung mặt vàng
            else:  # ✅ **Mắt mở**
                frame = draw_text_vietnamese(frame, "Mắt mở - An toàn", (x + 5, y - 10), (0, 255, 0))  # ✅ Chữ xanh
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)  # ✅ Khung mặt xanh

            break  # Chỉ xử lý khuôn mặt đầu tiên

        with lock:
            video_frame = frame.copy()


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
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    username = session.get('username') or get_current_username()
    return render_template(
        'index_flask_server.html',
        camera_id=camera_id,
        user_id=session.get('user_id'),
        username=username,
        contract_address=CONTRACT_ADDRESS,
        contract_abi=CONTRACT_ABI
    )

# ============ BLOCKCHAIN API ROUTES ============

@app.route('/api/auth/login', methods=['GET', 'POST'])
def api_auth_login():
    """Đăng nhập người dùng"""
    global current_user_id, current_user_token

    if request.method == 'GET':
        username = request.args.get('username')
        password = request.args.get('password')
        if not username or not password:
            return jsonify({
                'success': False,
                'message': 'Sử dụng POST với JSON {"username": ..., "password": ...} hoặc GET với ?username=...&password=...'
            }), 200
    else:
        data = request.get_json()
        username = data.get('username') if data else None
        password = data.get('password') if data else None

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
def api_auth_logout():
    """Đăng xuất"""
    global current_user_id, current_user_token
    if current_user_id:
        user_manager.log_access(current_user_id, 'logout', 'system', 'success')
        blockchain.add_access_log(current_user_id, 'user_logout', 'system')
        current_user_id = None
        current_user_token = None
    return jsonify({'success': True, 'message': 'Đã đăng xuất'}), 200


@app.route('/api/events/drowsiness', methods=['GET'])
def get_drowsiness_events():
    """Lấy danh sách các sự kiện phát hiện buồn ngủ"""
    active_user = session.get('user_id') or user_id
    days = request.args.get('days', default=None, type=int)
    if 'user_id' in session:
        user_manager.log_access(session['user_id'], 'view_events', 'drowsiness_events', 'success')
    events = blockchain.get_drowsiness_events(active_user, days)
    for event in events:
        image_path = event.get('image_path')
        if image_path:
            event['image_url'] = url_for('captured_image', filename=os.path.basename(image_path))

    return jsonify({
        'success': True,
        'total_events': len(events),
        'events': events
    }), 200


@app.route('/api/contract/info', methods=['GET'])
def api_contract_info():
    """API trả về address và ABI của contract để frontend có thể tương tác qua MetaMask"""
    return jsonify({
        'address': CONTRACT_ADDRESS,
        'abi': CONTRACT_ABI
    }), 200


@app.route('/api/user/history', methods=['GET'])
def get_user_history():
    """Lấy toàn bộ lịch sử của người dùng từ blockchain (Kiểm toán)"""
    active_user = session.get('user_id') or user_id
    if 'user_id' in session:
        user_manager.log_access(session['user_id'], 'view_history', 'blockchain_history', 'success')
    history = blockchain.get_user_history(active_user)
    return jsonify({
        'success': True,
        'total_records': len(history),
        'history': history
    }), 200


@app.route('/api/blockchain/status', methods=['GET'])
def blockchain_status():
    """Lấy trạng thái blockchain"""
    if 'user_id' in session:
        user_manager.log_access(session['user_id'], 'view_status', 'blockchain_status', 'success')
    return jsonify({
        'success': True,
        'total_blocks': len(blockchain.chain),
        'pending_transactions': len(blockchain.pending_transactions),
        'is_valid': blockchain.is_chain_valid(),
        'latest_block_hash': blockchain.get_latest_block().hash[:16] + '...'
    }), 200


@app.route('/api/ethereum/status', methods=['GET'])
def ethereum_status():
    """Lấy trạng thái kết nối Ethereum"""
    if 'user_id' in session:
        user_manager.log_access(session['user_id'], 'view_ethereum_status', 'ethereum_status', 'success')
    return jsonify({
        'success': True,
        'is_connected': web3.is_connected(),
        'network': web3.eth.chain_id if web3.is_connected() else None,
        'contract_address': CONTRACT_ADDRESS,
        'event_count': contract.functions.getEventCount().call() if web3.is_connected() else 0
    }), 200

if __name__ == '__main__':
    camera_thread = Thread(target=camera_stream, daemon=True)
    camera_thread.start()
    
    # Khởi chạy blockchain mining thread
    blockchain_thread = Thread(target=mine_blockchain, daemon=True)
    blockchain_thread.start()
    
    try:
        print("\n" + "="*60)
        print(f"✅ {SYSTEM_NAME}")
        print("="*60)
        print(f"📹 Camera ID: {camera_id}")
        print(f"👤 User ID (default): {user_id}")
        print(f"⛓️  Local Blockchain: Active")
        print(f"🔗 Ethereum: {'Connected' if web3.is_connected() else 'Disconnected'}")
        print(f"📄 Contract: {CONTRACT_ADDRESS}")
        print(f"🔗 API Endpoints:")
        print(f"   - POST   /api/auth/login")
        print(f"   - POST   /api/auth/logout")
        print(f"   - GET    /api/events/drowsiness")
        print(f"   - GET    /api/user/history")
        print(f"   - GET    /api/blockchain/status")
        print(f"   - GET    /api/ethereum/status")
        print(f"   - POST   /api/blockchain/mine")
        print(f"🌐 Web: http://0.0.0.0:5000")
        print("="*60 + "\n")
        
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    finally:
        if cap.isOpened():
            cap.release()
        print("\n" + "="*60)
        print("📊 BLOCKCHAIN AUDIT REPORT")
        print("="*60)
        print(f"✓ Tổng khối: {len(blockchain.chain)}")
        print(f"✓ Blockchain hợp lệ: {blockchain.is_chain_valid()}")
        print(f"\n📋 Lịch sử sự kiện phát hiện buồn ngủ:")
        events = blockchain.get_drowsiness_events(user_id=user_id)
        for event in events:
            print(f"   - Block #{event['block_index']}: {event['detected_at']} (Level: {event['alert_level']})")
        print("="*60 + "\n")
