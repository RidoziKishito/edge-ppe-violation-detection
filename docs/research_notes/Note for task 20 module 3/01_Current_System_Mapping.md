# 01 - Đối chiếu pipeline cũ và xác định phần giữ lại

## 1. Pipeline hiện tại thực sự làm gì

```text
YOLO inference
  -> tách Person và các detection PPE/no_PPE
  -> với từng Person: lấy foot-point để kiểm tra polygon zone
  -> tìm no_PPE có tâm nằm trong person box
  -> suy ra NORMAL/WARNING/CRITICAL
  -> chỉ giữ cảnh báo cao nhất theo zone
  -> temporal smoothing theo zone_id
  -> ghi events.csv + snapshot + output.mp4
```

Các điểm nối đang nằm tại:

- `edge-pipeline/edge_infer.py`: inference, duyệt từng person và tạo cảnh báo theo frame.
- `edge-pipeline/rule_engine.py`: kiểm tra polygon, gán `no_PPE` bằng tâm box và phân loại cảnh báo.
- `edge-pipeline/pipeline_control.py`: làm mượt cảnh báo nhưng đang lưu trạng thái theo `zone_id`.
- `edge-pipeline/logger.py`: ghi CSV và snapshot nhưng chưa có `run_id`, `track_id`, `event_id` hoặc action của sự kiện.
- `dashboard/workflow.py`: đã tạo `run_id`, thư mục run, video đầu ra và bản sao zone cho mỗi lần chạy.

## 2. Phần tốt cần giữ

| Thành phần cũ | Quyết định | Cách dùng trong thiết kế mới |
|---|---|---|
| Một lần YOLO trả Person và PPE/no_PPE | Giữ | Không chạy thêm detector chỉ để tạo WorkerState. |
| Tâm PPE/no_PPE nằm trong person box | Giữ làm association baseline | Sau khi gán box cho person, kết quả được gắn vào `track_id`. |
| Foot-point của person | Giữ | Tiếp tục dùng để xác định `zone_ids`; không cần homography. |
| Polygon warning/danger zone | Giữ | Zone là thuộc tính của WorkerState và là đầu vào tính severity. |
| `NORMAL/WARNING/CRITICAL` | Giữ | Trở thành severity của WorkerEvent, không dùng làm danh tính sự kiện. |
| Temporal confirmation và cooldown | Giữ ý tưởng | Đổi khóa từ `zone_id` sang từng worker + từng PPE. |
| CSV, snapshot, output video | Giữ | Bổ sung trường mới nhưng không phá dashboard và run archive hiện tại. |
| `run_id` của dashboard | Giữ | Đưa vào worker key/event key để tránh trùng ID giữa hai video. |

## 3. Phần không còn đủ cho worker-level event

| Hạn chế hiện tại | Hậu quả | Thiết kế Task 20 xử lý |
|---|---|---|
| Person không có `track_id` | Không biết person ở hai frame có phải cùng người hay không. | Định nghĩa `WorkerTrack`; ByteTrack sẽ được tích hợp ở Task 22. |
| Temporal state được khóa bằng `zone_id` | Hai công nhân trong cùng zone có thể bị gom thành một cảnh báo. | Sự kiện được khóa bằng camera + run + track + PPE + loại vi phạm. |
| `check_ppe_violation()` chỉ trả chuỗi `no_helmet`, ... | Không có confidence, owner, visibility hoặc lý do kết luận. | Chuẩn hóa thành PPE evidence và PPE state có reason code. |
| Không phát hiện `no_PPE` thì ngầm xem như không vi phạm | Dễ nhầm “không nhìn thấy” với “đang mặc”. | Bắt buộc có `UNKNOWN`; chỉ evidence hợp lệ mới tạo `WORN/NOT_WORN`. |
| Logger gộp nhiều violation trong một chuỗi | Không quản lý được thời điểm bắt đầu/kết thúc riêng cho helmet và gloves. | Một WorkerEvent ứng với một worker và một PPE violation. |
| Cảnh báo cao nhất được giữ theo zone | Có thể làm mất bằng chứng của worker khác hoặc PPE khác. | WorkerState/Event tồn tại độc lập; zone chỉ ảnh hưởng severity. |

## 4. Ánh xạ output hiện tại sang contract mới

| Output hiện tại | Trường mới | Ghi chú |
|---|---|---|
| `camera_id` | `camera_id` | Giữ nguyên. |
| Thư mục run của dashboard | `run_id` | `dashboard/workflow.py` đã tạo nhưng pipeline cần nhận rõ giá trị này. |
| `frame_id` | `frame_id` | Giữ nguyên. |
| Thời điểm video/frame | `timestamp_ms` | Dùng timeline video; không chỉ dùng giờ hệ thống ghi log. |
| Person box/confidence | `person.box`, `person.confidence` | Được ByteTrack gắn `track_id` ở Task 22. |
| Tâm đáy person box | `person.foot_point` | Giữ cách tính hiện tại. |
| Zone chứa foot-point | `zone_ids` | Có thể có nhiều zone; không dùng zone làm worker key. |
| PPE/no_PPE box | `ppe.*.evidence` | Chỉ trở thành state sau association và visibility check. |
| `alert_level` | `WorkerEvent.severity` | Vẫn dùng luật phân loại cũ. |
| `violation_type` | `ppe_type` + `violation_type` | Tách rõ PPE nào và điều kiện vi phạm nào. |
| `bbox` | `person.box` hoặc `evidence.box` | Không dùng một trường mơ hồ cho hai loại box. |

## 5. Những điều Task 20 không giả vờ giải quyết

- Chưa có tracker trong runtime, vì vậy contract yêu cầu `track_id` nhưng không tạo ID giả từ số thứ tự person box.
- Chưa có visibility/occlusion model; schema chỉ dành chỗ cho kết quả này. Hệ thống chỉ được phát reason code khi có rule/module tương ứng.
- Nhãn `none` không cho biết thiếu loại PPE nào nên không map sang `NOT_WORN`.
- Dataset v1 không có `no_vest`; không detect `vest` không đồng nghĩa với `vest=NOT_WORN`.
- Không thay luật tâm box bằng pose hoặc matching phức tạp trong task này.

## Kết luận bước 1

Task 20 không thay detector hay giao diện hiện tại. Nó thêm một lớp contract giữa detection và alert để các thành phần cũ tiếp tục dùng được, đồng thời loại bỏ việc đồng nhất worker với person box của một frame hoặc với một polygon zone.
