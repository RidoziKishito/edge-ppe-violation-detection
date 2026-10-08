# 05 - System-method matrix and research architecture

## 1. System-method matrix

| Khối | Trạng thái | Phương pháp | Dữ liệu | Metric |
|---|---|---|---|---|
| Multi-PPE detection | Cũ, giữ | YOLO 11 lớp | Dataset v1 đã audit | mAP50-95, recall/class |
| Small-object robustness | Mới, có gate | P2 ở Module 1; SAHI hoặc person-crop ở inference | robustness_v1 | AP_small, recall/class, latency |
| Low-light/blur robustness | Mới, core | train augmentation + conditional enhancement/quality gate | robustness_v1 | relative degradation, false negative rate, latency |
| Person tracking | Mới, core | ByteTrack | CMOT + PPE-MOT-mini | HOTA, AssA, IDF1, IDSW |
| Box-only association | Baseline | PPE center trong person box | PPE-MOT-mini | owner accuracy, false assignment rate |
| Visibility-aware state | Mới, core | boundary/body-region visibility gate; không cần pose | PPE-MOT-mini + robustness_v1 | UNKNOWN accuracy, false violation rate |
| PPE state theo worker | Mới, core | WORN/NOT_WORN/UNKNOWN; CARRIED nếu có dữ liệu | PPE-MOT-mini | macro-F1, violation recall |
| Temporal event | Nâng cấp từ cũ | State machine theo track | PPE-MOT-mini | event P/R/F1, onset delay |
| Polygon zone | Cũ, giữ | Foot-point + point-in-polygon | Zone config hiện tại | zone assignment accuracy |
| Edge deployment | Cũ, bắt buộc đo lại | ONNX/FP16, batch 1, end-to-end | Test video + Jetson mục tiêu | FPS, P50/P95, RAM/VRAM, dropped frames, power/temperature nếu có |
| Logger/dashboard | Cũ, mở rộng | Worker-level event | Runtime output | duplicate event rate |
| Metric-2D/TTC/dynamic risk | Future Work | Chưa triển khai | Chưa có dataset phù hợp | Chưa đánh giá |

## 2. Kiến trúc triển khai

```text
[Frame]
   |
[Quality assessment: brightness / blur / boundary]
   |-- conditional CLAHE/gamma khi tối
   |-- SAHI hoặc person-crop theo cấu hình small-object
   v
[YOLO detector + merge NMS]
   | person boxes                         | PPE/no_PPE boxes
   v                                      |
[ByteTrack]                               |
   | WorkerTrack(track_id, bbox, history) |
   +----------------------+---------------+
                          v
                 [Center containment]
                          |
                  [Visibility gate]
                          |
                    state per track
                          v
               [Temporal event FSM]
                          |
               [Existing polygon zone]
                          |
             logger / snapshot / dashboard
```

FSM lưu trạng thái theo thời gian để không tạo một cảnh báo mới ở mọi frame.

## 3. Thí nghiệm tối thiểu

| ID | Cấu hình | Câu hỏi |
|---|---|---|
| E0 | Project cũ, không tracking | Frame-level baseline sai ở đâu? |
| E1 | Baseline/P2 + SAHI hoặc person-crop | AP_small tăng bao nhiêu và latency tăng bao nhiêu? |
| E2 | E1 + low-light/motion-blur training recipe | Độ suy giảm theo corruption có giảm không? |
| E3 | Detector đã chọn + ByteTrack | ID có đủ ổn định và đạt ngân sách edge không? |
| E4 | E3 + center containment + visibility gate | Có giảm false violation khi vùng cơ thể ngoài ảnh/không rõ không? |
| E5 | E4 + per-track FSM | Worker-level event có giảm cảnh báo trùng/chớp tắt không? |

Mỗi thí nghiệm phải báo cả chất lượng và chi phí Edge AI. `131.4 FPS @ batch 8` của báo cáo cũ chỉ là mốc tham khảo model throughput, không phải baseline end-to-end. Cấu hình release được chọn bằng batch 1 trên video/camera thật; không giữ feature chỉ vì demo trực quan đẹp.

## 4. Đầu ra

### Tracking

- `WorkerTrack` schema và tracker config.
- Video overlay ID và MOT-format predictions.
- HOTA, DetA, AssA, IDF1, IDSW và latency.

### Worker-PPE association và event

- Center-containment baseline và visibility gate.
- State theo `(camera_id, track_id, ppe_type)`.
- Worker-level event log.
- Owner accuracy, state F1, event P/R/F1 và onset delay.

### Tích hợp

- Polygon zone cũ tiếp tục hoạt động.
- Logger, snapshot và dashboard hiển thị `track_id` cùng PPE state.
- Có benchmark end-to-end sau tích hợp.
- Benchmark ghi rõ thiết bị, backend, precision, input size, batch, inference interval và các thành phần được tính trong latency.

## 5. Hoàn thành Task 3 khi

- Phân biệt rõ phần cũ nên giữ, phần mới thuộc core và Future Work.
- Có luồng `detector -> tracker -> association -> temporal event`.
- Có luồng robustness `quality assessment -> conditional preprocessing/small-object inference -> detector` và protocol đánh giá riêng.
- Có kế hoạch `PPE-MOT-mini`, annotation schema và protocol chia tập.
- Có metric và thí nghiệm so sánh baseline.
- Metric-2D, máy móc, TTC và dynamic risk không nằm trong critical path.
- Có Keep/Conditional/Future-Work gate để giới hạn tính năng theo ngân sách Jetson nhẹ.

## 6. Nguồn chính

- ByteTrack: https://github.com/FoundationVision/ByteTrack
- HOTA: https://arxiv.org/abs/2009.07736
- TrackEval: https://github.com/JonathonLuiten/TrackEval
- TCSS-Net local reference: `D:/UTE/TLCN/references/feart-14-1878141.pdf`
- CMOT: https://github.com/XZ-YAN/CMOT-Dataset
- SH17: https://github.com/ahmadmughees/SH17dataset
- CVAT auto annotation: https://docs.cvat.ai/docs/annotation/auto-annotation/
- SAHI: https://arxiv.org/abs/2202.06934
- Zero-DCE: https://openaccess.thecvf.com/content_CVPR_2020/html/Guo_Zero-Reference_Deep_Curve_Estimation_for_Low-Light_Image_Enhancement_CVPR_2020_paper.html
- Motion-blur object detection: https://openaccess.thecvf.com/content/CVPR2021/html/Sayed_Improved_Handling_of_Motion_Blur_in_Online_Object_Detection_CVPR_2021_paper.html
