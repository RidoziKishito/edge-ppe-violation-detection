# 04 - WorkerEvent và vòng đời sự kiện

## 1. Vì sao cần tách WorkerState và WorkerEvent

- `WorkerState` mô tả một inference frame.
- `WorkerEvent` gom nhiều WorkerState liên tiếp thành một vi phạm có bắt đầu, cập nhật và kết thúc.

Nếu không tách hai lớp này, mỗi frame có `no_helmet` sẽ tạo một log mới. Ngược lại, nếu chỉ gom theo zone như hiện tại, hai worker cùng trong `Z01` có thể bị coi là một sự kiện.

## 2. Khóa sự kiện

```text
event_key = camera_id + run_id + track_id + ppe_type + violation_type
```

Hệ quả:

- cùng worker vi phạm helmet và gloves -> hai event riêng;
- hai worker trong cùng zone -> hai event riêng;
- cùng `track_id` nhưng khác video -> hai event riêng vì `run_id` khác;
- worker đổi zone -> event PPE vẫn là event cũ, chỉ cập nhật zone/severity.

`event_id` là ID duy nhất của một lần event được mở; `event_key` là khóa logic dùng để tìm state machine tương ứng.

## 3. State machine nội bộ và record phát ra

Không nên xem `Updated` là một trạng thái tồn tại lâu hoặc xem cooldown là một event. Thiết kế rõ hơn là:

### Trạng thái nội bộ

```text
IDLE -> CANDIDATE -> ACTIVE -> COOLDOWN -> IDLE
```

### Action ghi ra logger/dashboard

```text
START | UPDATE | END
```

| Tình huống | Chuyển trạng thái | Action |
|---|---|---|
| Frame đầu có `NOT_WORN` | `IDLE -> CANDIDATE` | Chưa log cảnh báo chắc chắn. |
| `NOT_WORN` đủ số inference frame/dwell time | `CANDIDATE -> ACTIVE` | `START` |
| Cùng vi phạm nhưng zone, severity hoặc evidence quan trọng đổi | `ACTIVE -> ACTIVE` | `UPDATE` khi giá trị thực sự đổi; không log mỗi frame. |
| State trở lại `WORN` ổn định | `ACTIVE -> COOLDOWN` | `END/COMPLIANCE_RESTORED` |
| Track tạm `LOST` | Giữ `ACTIVE` trong grace window | Không mở event mới; có thể cập nhật trạng thái nội bộ. |
| Track `REMOVED` | `ACTIVE -> COOLDOWN` | `END/TRACK_ENDED` |
| Run kết thúc | kết thúc mọi event active | `END/RUN_ENDED` |
| Trong cooldown lại có detection chớp nhoáng | giữ `COOLDOWN` | Không tạo event trùng. |
| Cooldown hết và vi phạm lại đủ dwell | tạo event_id mới | `START` mới. |

Đếm dwell theo **inference frame**, không theo display frame, vì project hiện có `inference_interval`.

## 4. Quy tắc với UNKNOWN

- `UNKNOWN` không mở event mới.
- `UNKNOWN` ngắn trong khi event đang active không tự đóng event.
- Nếu `UNKNOWN` kéo dài đến khi track bị `REMOVED`, event kết thúc bằng `TRACK_ENDED`, không phải `COMPLIANCE_RESTORED`.
- Hệ thống chỉ kết luận đã khắc phục khi có `WORN` ổn định hoặc một end condition được định nghĩa rõ.

Đây là điểm khác biệt quan trọng giữa “không còn nhìn thấy vi phạm” và “đã thấy worker mặc lại PPE”.

## 5. Severity tiếp tục dùng luật cũ

Task 20 không thay business rule của `classify_alert()`:

- có vi phạm trong warning/danger zone -> `CRITICAL`;
- ở trong warning/danger zone nhưng chưa có vi phạm -> `WARNING` ở level frame hiện tại;
- vi phạm ngoài zone -> `WARNING`;
- không zone, không vi phạm -> `NORMAL`.

Đối với WorkerEvent PPE, zone thay đổi chỉ làm event `UPDATE` severity; không đổi owner hoặc tạo event mới.

## 6. WorkerEvent schema

```json
{
  "schema_version": "1.0",
  "event_id": "evt_20261009_000021",
  "event_key": "0003/run_20261009_001/7/helmet/NOT_WORN",
  "action": "START",
  "status": "ACTIVE",
  "camera_id": "0003",
  "run_id": "run_20261009_001",
  "track_id": 7,
  "ppe_type": "helmet",
  "violation_type": "NOT_WORN",
  "severity": "CRITICAL",
  "zone_ids": ["Z01"],
  "start_frame": 148,
  "current_frame": 152,
  "end_frame": null,
  "start_timestamp_ms": 4933,
  "current_timestamp_ms": 5066,
  "end_timestamp_ms": null,
  "duration_ms": 133,
  "evidence": {
    "person_box": [412, 121, 621, 691],
    "ppe_box": [466, 130, 532, 205],
    "detection_class": "no_helmet",
    "confidence": 0.88,
    "association_method": "CENTER_CONTAINMENT",
    "association_confidence": 0.92,
    "snapshot_path": "snapshots/evt_20261009_000021_start.jpg"
  },
  "reason_code": "NEGATIVE_LABEL_DETECTED"
}
```

Khi kết thúc, cùng `event_id` được ghi với `action=END`, `status=RESOLVED`, có `end_frame`, `end_timestamp_ms`, `duration_ms` cuối và một trong các reason code:

```text
COMPLIANCE_RESTORED | TRACK_ENDED | RUN_ENDED
```

## 7. Chống log trùng

- Snapshot mặc định chụp ở `START`, tùy chọn thêm khi severity tăng hoặc `END`; không lưu ảnh ở mọi frame.
- `UPDATE` chỉ phát khi zone, severity, PPE state hoặc evidence chính thay đổi đáng kể.
- Cooldown được khóa theo `event_key`, không theo zone.
- `event_id` không đổi trong suốt vòng đời của một event.
- Không gộp nhiều PPE vào một chuỗi violation duy nhất ở lớp event.

## Kết luận bước 4

Vòng đời mới kế thừa dwell/cooldown của `TemporalSmoother` nhưng thay đơn vị theo dõi từ polygon zone sang đúng worker/PPE. Nhờ đó logger có thể giải thích một vi phạm kéo dài thay vì chỉ lưu các alert rời rạc.
