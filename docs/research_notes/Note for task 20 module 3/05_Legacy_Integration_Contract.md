# 05 - Điểm nối với hệ thống cũ

## 1. Luồng tích hợp mục tiêu

```text
edge_infer.py
  infer_detections()
      |
      +-- Person detections --> PersonTracker adapter --> WorkerTrack[]
      |
      +-- PPE/no_PPE detections ---------------------------+
                                                           v
rule_engine.py                                      WorkerStateBuilder
  center containment + foot-point + zone                  |
                                                           v
pipeline_control.py                                  WorkerState[]
  WorkerEventEngine(event_key, dwell, cooldown)            |
                                                           v
logger.py                                            WorkerEvent[]
  CSV/snapshot + structured event fields                    |
                                                           v
dashboard/run archive                                UI + output.mp4
```

Task 20 chỉ chốt interface. Việc viết `PersonTracker` diễn ra ở Task 22; data/evaluation bắt đầu từ Task 21/23.

## 2. Contract giữa các thành phần

### Detector -> tracker

- Input: chỉ các detection có `class_name=Person`, gồm box và confidence.
- Output: `WorkerTrack[]` có `track_id`, box, confidence và track status.
- PPE/no_PPE boxes không đi vào tracker.

### Tracker + PPE detections + zone config -> WorkerStateBuilder

- Với mỗi WorkerTrack, dùng person box hiện tại làm owner candidate.
- Giữ baseline: tâm PPE/no_PPE nằm trong person box.
- Nếu box có nhiều owner hợp lệ mà chưa có tie-break đáng tin cậy, trả unassigned/`AMBIGUOUS_OWNER`, không nhân đôi evidence cho hai worker.
- Tính foot-point và `zone_ids` bằng code polygon hiện tại.
- Tạo một PPE record riêng cho helmet, goggles, vest, gloves và boots.

### WorkerState -> WorkerEventEngine

- Chỉ `CONFIRMED` track có thể mở event.
- Chỉ `NOT_WORN` có evidence hợp lệ mới đi vào candidate.
- `WORN` ổn định có thể đóng event.
- `UNKNOWN` giữ trạng thái thận trọng, không mở vi phạm mới.
- Khóa temporal state bằng `event_key`, không bằng `zone_id`.

### WorkerEvent -> logger/dashboard

- Logger nhận event action `START/UPDATE/END`.
- Dashboard vẫn có thể đọc các cột cũ trong giai đoạn chuyển đổi.
- Video renderer vẫn vẽ person/PPE/zone như hiện tại; bổ sung `track_id` khi tracker được bật.

## 3. Thay đổi tối thiểu theo file

| File/thành phần | Giữ lại | Bổ sung sau Task 20 |
|---|---|---|
| `edge-pipeline/edge_infer.py` | Model loading, inference, video loop, renderer, output writer | Adapter tracker, WorkerStateBuilder và đường dữ liệu WorkerEvent. |
| `edge-pipeline/rule_engine.py` | `point_in_polygon`, `get_person_zones`, `classify_alert`, center containment | Trả association evidence có cấu trúc thay vì chỉ danh sách chuỗi. |
| `edge-pipeline/pipeline_control.py` | `required_frames`, cooldown, inference interval | Thêm `WorkerEventEngine`; giữ `TemporalSmoother` cũ dưới feature flag trong giai đoạn so sánh. |
| `edge-pipeline/logger.py` | CSV, snapshot, tên camera/frame/zone/severity | Thêm run/event/track/PPE/action/reason fields. |
| `dashboard/workflow.py` | Tạo run folder, `run_id`, progress, output.mp4, zones snapshot | Truyền `run_id` rõ vào pipeline command. |
| `dashboard/app.py` | Run history, events API, download artefacts | Hiển thị event action/track/PPE nếu field có mặt; vẫn đọc log cũ. |

## 4. Logger v1.1 tương thích ngược

Giữ nguyên các cột đầu để dashboard cũ tiếp tục đọc:

```text
timestamp,camera_id,frame_id,zone_id,alert_level,
violation_type,confidence,bbox,snapshot_path
```

Nối thêm các cột có cấu trúc:

```text
schema_version,run_id,event_id,event_action,event_status,
track_id,worker_key,ppe_type,ppe_state,association_method,
association_confidence,visibility,reason_code,start_frame,
end_frame,duration_ms
```

Quy ước:

- `violation_type` cũ vẫn chứa tên dễ đọc như `no_helmet` để UI cũ không hỏng.
- Các cột mới là nguồn đúng cho UI worker-centric.
- Không ghi toàn bộ WorkerState mỗi frame vào CSV production. Nếu cần debug, dùng `worker_states.jsonl` có cờ bật/tắt và giới hạn thời gian.
- Mỗi event action là một row; `event_id` nối các row `START/UPDATE/END`.

## 5. Lộ trình chuyển đổi an toàn

### Giai đoạn A - Contract only (Task 20)

Chốt tài liệu, schema, enum, mapping và interface. Runtime cũ chưa thay đổi.

### Giai đoạn B - Tracker có feature flag (Task 22)

Thêm cấu hình `tracking.enabled`. Khi tắt, image inference và demo cũ vẫn chạy. Khi bật, Person có `track_id` nhưng alert cũ vẫn có thể chạy song song.

### Giai đoạn C - Shadow WorkerState/Event

Sinh WorkerState/Event ở chế độ shadow: lưu log mới để so sánh nhưng chưa thay cảnh báo UI. Mục tiêu là phát hiện lỗi contract và log trùng mà không phá demo.

### Giai đoạn D - Chuyển dashboard sang event mới

Chỉ chuyển sau khi contract tests và video validation đạt yêu cầu. Renderer, polygon editor, run archive và output video được giữ nguyên.

## 6. Trường hợp phải xử lý khi triển khai

1. Cùng worker chuyển từ `no_helmet` sang `helmet`: giữ `track_id`, event kết thúc bằng `COMPLIANCE_RESTORED`.
2. Đầu ngoài ảnh: helmet là `UNKNOWN`, không phải `NOT_WORN`.
3. Track mất ngắn rồi quay lại: không tạo event trùng.
4. Track bị `REMOVED`: đóng event bằng `TRACK_ENDED`.
5. Một worker vi phạm helmet và gloves: hai event riêng.
6. Hai worker cùng danger zone: không bị gom thành một event.
7. Chọn video mới: tạo `run_id` mới và reset tracker/event engine.
8. PPE box không có owner: chỉ tạo UnassignedPPEEvidence.
9. Không detect vest: không kết luận `NOT_WORN` vì model không có `no_vest`.
10. `none` detection: không tự map sang bất kỳ PPE violation nào.

## 7. Definition of done cho thiết kế bước 1-5

- Đã chỉ ra field nào lấy trực tiếp từ hệ thống cũ và field nào cần task sau cung cấp.
- Worker key và event key không phụ thuộc vào zone.
- `UNKNOWN`, `LOST`, `REMOVED` và unassigned evidence có hành vi rõ ràng.
- Schema không yêu cầu pose, ReID hoặc homography.
- Logger mới có đường tương thích với CSV/dashboard hiện tại.
- Việc tích hợp ByteTrack, tạo video ground truth, tuning association và đánh giá event vẫn thuộc Task 21–26, không bị kéo vào Task 20.

## Kết luận bước 5

Thiết kế mới không viết lại project. Nó chèn một lớp `WorkerState -> WorkerEvent` vào đúng giữa detection/rule hiện tại và logger/dashboard hiện tại. Đây là thay đổi nhỏ nhất để tiến từ cảnh báo theo box/zone sang cảnh báo theo từng worker mà vẫn giữ giá trị Edge AI và demo cũ.
