# Smart Traffic Safety

Hệ thống giám sát an toàn giao thông thông minh cho tài xế dựa trên camera, OpenCV, Flask và lớp ghi nhận sự kiện bằng blockchain nội bộ. Khi phát hiện mắt nhắm hoặc dấu hiệu buồn ngủ, hệ thống sẽ cảnh báo tức thì, chụp ảnh và lưu sự kiện để theo dõi sau này.

## Tính năng chính
- Phát hiện buồn ngủ theo khung hình camera thời gian thực.
- Cảnh báo tức thì bằng âm thanh và hiển thị overlay trên video.
- Lưu ảnh sự kiện vào `captured_images/`.
- Ghi nhận sự kiện vào local blockchain để kiểm tra lịch sử.
- Giao diện web để xem video trực tiếp và trạng thái hệ thống.

## Cấu trúc chính
- `importcv2.py`: ứng dụng Flask chính cho Smart Traffic Safety.
- `motion_detection.py`: bộ khởi chạy tương thích, chuyển hướng sang ứng dụng chính.
- `start_server.bat`: file chạy nhanh trên Windows.
- `templates/index_flask_server.html`: giao diện dashboard.
- `train_latest_drowsiness_model.py`: script huấn luyện transfer learning cho model mới.
- `blockchain.py`: lưu sự kiện drowsiness vào chuỗi khối nội bộ.
- `user_identity.py`: quản lý người dùng và phiên đăng nhập.

## Cài đặt
```bash
pip install -r requirements.txt
```

Nếu bạn dùng các bản mở rộng như `thu5.py` hoặc `testAmThanh.py`, hãy cài thêm `tensorflow`, `gTTS`, `pygame`, `Pillow` và `playsound` theo nhu cầu.

## 4.5 Kết nối MetaMask
- Cài đặt MetaMask trên trình duyệt và chuyển sang mạng `Sepolia`.
- Đảm bảo ví có đủ test ETH để ký và gửi giao dịch.
- Mở giao diện web, bấm `Kết nối MetaMask` rồi xác nhận ví.
- Ứng dụng sẽ dùng `CONTRACT_ADDRESS` từ máy chủ để tránh ghi đè sai ở trình duyệt.

## 4.6 Triển khai smart contract
- Compile và deploy `DrowsinessDetection.sol` bằng Remix hoặc `deploy_contract.py`.
- Sao chép địa chỉ contract vừa deploy vào biến môi trường `CONTRACT_ADDRESS` trong `.env`.
- Khởi động lại ứng dụng sau khi cập nhật `.env` để frontend và backend dùng cùng một địa chỉ.
- Nếu đổi contract mới, cần reload trang để MetaMask gọi đúng ABI và address.

## Huấn luyện model mới
Khi có dataset, bạn có thể train model mới bằng script:
```bash
python train_latest_drowsiness_model.py --data-dir dataset --output models/drowsiness_latest.keras
```

Dataset nên được tổ chức theo thư mục lớp, ví dụ:
```text
dataset/
	open/
	closed/
	yawning/
	distracted/
```

Nếu TensorFlow chưa được cài trong môi trường hiện tại, script sẽ báo rõ và dừng an toàn.

## Chạy hệ thống
```bash
python motion_detection.py
```

Mặc định, app dùng MediaPipe Face Mesh để phát hiện mắt nhắm. Nếu muốn đổi mode, đặt biến môi trường:
```bash
set DETECTION_MODE=mediapipe
```

Nếu muốn dùng YOLOv8, đặt `DETECTION_MODE=yolov8` và `YOLO_MODEL_PATH=models/drowsiness_yolov8.pt`.

Nếu chưa có `mediapipe` hoặc `ultralytics`, ứng dụng sẽ tự quay về chế độ Haar cascade để vẫn chạy được.

Hoặc trên Windows:
```bat
start_server.bat
```

Bạn có thể truyền camera URL qua biến môi trường `CAMERA_URL` hoặc tham số đầu tiên của `start_server.bat`.

## Luồng hoạt động
1. Nhận khung hình từ camera hoặc điện thoại qua `CAMERA_URL`.
2. Phát hiện khuôn mặt, mắt và tư thế đầu.
3. Nếu dấu hiệu buồn ngủ kéo dài vượt ngưỡng, hệ thống chụp ảnh và phát cảnh báo.
4. Sự kiện được xếp hàng chờ MetaMask ký giao dịch, sau đó được ghi lên smart contract và hiển thị trên dashboard.

## 5.5 Gửi cảnh báo qua MetaMask
- Backend đẩy sự kiện buồn ngủ vào hàng đợi `/api/metamask/next-alert`.
- Frontend lấy từng cảnh báo, tạo giao dịch `addDrowsinessEvent(...)` và yêu cầu MetaMask ký.
- Khi giao dịch được xác nhận, frontend gọi `/api/metamask/ack-alert` để đánh dấu đã xử lý.
- Toàn bộ địa chỉ contract lấy từ server, không phụ thuộc `localStorage` của trình duyệt.

## Ghi chú
- Các script như `thu5.py`, `test8.py`, `testAmThanh.py` là biến thể thử nghiệm hoặc mở rộng.
- Nếu muốn xem tích hợp MetaMask/Smart Contract, đọc thêm `README_MetaMask.md`.

© 2025 NHÓM 2, CNTT16-04, TRƯỜNG ĐẠI HỌC ĐẠI NAM