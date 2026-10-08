# 01 - Project baseline and final scope

## 1. Feature cũ nên giữ

| Feature | Giá trị sau nâng cấp |
|---|---|
| YOLO 11 lớp | Tiếp tục làm detector `Person`, PPE và `no_*` |
| Polygon danger/warning zone | Giữ làm kiểm tra vùng nguy hiểm theo camera |
| Foot-point của person box | Dùng để kiểm tra công nhân có nằm trong polygon hay không |
| Temporal smoothing | Chuyển từ theo zone sang theo `track_id + violation_type` |
| Logger và snapshot | Bổ sung `track_id`, PPE state và thời gian sự kiện |
| Dashboard | Hiển thị sự kiện theo từng công nhân |
| ONNX/FP16 và benchmark edge | Đo lại latency sau khi thêm tracker và association |

Project cũ có kiến trúc **Edge AI** vì inference, polygon rule, smoothing, log và dashboard đều có thể chạy cục bộ. Tuy nhiên hiện mới nên gọi là `edge-oriented`, chưa phải `edge-validated`: số 131.4 FPS trong báo cáo là model throughput ở batch 8 trên CUDA, không phải FPS end-to-end của camera đơn hay kết quả đã đo trên Jetson. Mọi cấu hình nâng cấp phải được đo lại ở batch 1 trên phần cứng mục tiêu.

## 2. Vấn đề cần giải quyết

1. Người/PPE nhỏ, ảnh tối và motion blur có thể làm detector bỏ sót; khi Person bị bỏ sót thì ByteTrack cũng không thể duy trì ID.
2. Không có `track_id`, vì vậy cùng một người có thể tạo nhiều cảnh báo rời rạc.
3. Temporal smoothing chưa giữ trạng thái độc lập cho từng công nhân.
4. Khi đầu, tay hoặc chân nằm ngoài ảnh hay bị che, hệ thống chưa có cổng visibility để phân biệt `không thấy` với `không mang`.
5. Dataset v1 thiếu `no_vest`, nên không thể kết luận không mặc vest chỉ vì detector không thấy vest.
6. Lớp `none` chưa có ý nghĩa an toàn rõ và không được xử lý nhất quán giữa inference và rule engine.

## 3. Feature mới thuộc phạm vi core

| Feature | Cách nối với project cũ |
|---|---|
| Robust detection controller | Đánh giá brightness/blur; chỉ tăng sáng hoặc đổi đường inference khi cần |
| Small-object inference | P2 thuộc Module 1; SAHI/person-crop là candidate để đo gain/latency, không mặc định chạy đồng thời |
| ByteTrack | Nhận person box từ YOLO và trả `track_id`; không cần train tracker mới |
| Center-containment association | Giữ rule tâm PPE nằm trong person box làm core; không thêm pose/Hungarian khi chưa có lỗi thực nghiệm |
| Visibility gate | Vùng PPE ngoài ảnh, bị che hoặc quá mờ trả `UNKNOWN`, không phát vi phạm mới |
| Worker PPE state | Chuyển detection rời thành trạng thái của từng `track_id` |
| Worker-level event | Tái sử dụng smoothing, logger, snapshot và dashboard hiện có |

## 4. Phạm vi PPE

| PPE | Quyết định |
|---|---|
| Helmet | Core: `WORN`, `NOT_WORN`, `UNKNOWN`; `CARRIED` chỉ đánh giá nếu có clip được gán nhãn rõ |
| Vest | Core: `WORN`, `UNKNOWN`; `NOT_WORN` chỉ khi có dữ liệu `no_vest` và vùng thân nhìn rõ |
| Goggles | Detection hiện có; association chỉ thử khi ảnh mặt đủ rõ |
| Gloves | Detection hiện có; association chỉ thử khi cổ tay đủ rõ |
| Boots | Detection hiện có; association chỉ thử khi chân đủ rõ |

## 5. Không đưa vào core

- Metric-2D/homography, detector và tracker máy móc, TTC và dynamic risk.
- Monocular depth hoặc 3D proximity.
- Full TCSS-Net/GNN và huấn luyện pose model mới; pose pretrained chỉ là nhánh thử nghiệm có điều kiện.
- Deblurring hoặc super-resolution sinh chi tiết trước khi cảnh báo an toàn; có nguy cơ tạo chi tiết giả và tăng latency.
- Multi-camera ReID, nhận diện danh tính và action recognition tổng quát.
- Sinh toàn bộ video hoặc test set bằng AI.

## 6. Đầu ra bắt buộc

- `track_id` ổn định cho công nhân.
- Có báo cáo theo size/low-light/blur/truncation và ablation cho phương pháp robustness được chọn.
- Helmet/vest được gán đúng `track_id`.
- Có `WORN`, `NOT_WORN`, `UNKNOWN` theo thời gian; `CARRIED` chỉ là state mở rộng nếu có clip và nhãn xác nhận.
- Mỗi vi phạm sinh một worker-level event có thời điểm bắt đầu và kết thúc.
- Polygon zone và các chức năng cũ vẫn hoạt động.
- Có metric tracking, association, event và edge latency.

## 7. Cổng thiết kế Edge AI

### Luôn chạy trong core

- YOLO PPE, polygon/foot-point, ByteTrack không ReID, center-containment, visibility gate, worker event, local logger/dashboard.
- `track_id` chỉ là ID tạm thời trong một camera/run; reset khi đổi nguồn hoặc reconnect. Không nhận diện danh tính.

### Chỉ bật có điều kiện

- Gamma/CLAHE khi frame dưới ngưỡng sáng.
- Chỉ chọn **SAHI hoặc person-crop** theo kết quả AP-small/latency; không mặc định chạy cả hai.
- Pose/Hungarian chỉ được mở lại nếu failure analysis chứng minh center-containment gây lỗi có hệ thống và giải pháp nhẹ không đủ.

### Future Work

- ReID nhiều camera, Metric-2D/homography, máy móc, TTC/dynamic risk, monocular depth, ergonomics/pose toàn thời gian và VLM.

### Metric bắt buộc khi tích hợp

- Chạy camera đơn, batch 1 và đo toàn pipeline: FPS, P50/P95 latency, RAM/VRAM, dropped frames.
- Nếu có Jetson: bổ sung công suất, nhiệt độ và thermal throttling trong phiên chạy dài.
- So E0 project cũ với từng cấu hình E1...; feature chỉ được giữ khi có gain định lượng và vẫn đạt ngân sách edge đã chốt.
- Model baseline tái lập hiện có tại `D:/UTE/TLCN/Models/baseline_yolo26n_best.onnx`; kết quả benchmark cũ không được dùng thay cho benchmark end-to-end mới.
