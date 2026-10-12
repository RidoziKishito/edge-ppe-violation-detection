# 03 - Thiết kế WorkerState

## 1. Vai trò

`WorkerState` là ảnh chụp trạng thái của **một worker track tại một inference frame**. Nó không phải log cảnh báo và không phải hồ sơ cá nhân. Mục đích là tạo ngôn ngữ chung cho tracker, association, zone rule và event engine.

## 2. Schema đề xuất

```json
{
  "schema_version": "1.0",
  "worker_key": "0003/run_20261009_001/7",
  "camera_id": "0003",
  "run_id": "run_20261009_001",
  "frame_id": 152,
  "timestamp_ms": 5066,
  "track_id": 7,
  "track_status": "CONFIRMED",
  "person": {
    "box": [412, 121, 621, 691],
    "confidence": 0.90,
    "foot_point": [516, 691]
  },
  "zone_ids": ["Z01"],
  "ppe": {
    "helmet": {
      "expected_region": "HEAD",
      "state": "NOT_WORN",
      "evidence_class": "no_helmet",
      "evidence_box": [466, 130, 532, 205],
      "confidence": 0.88,
      "visibility": "VISIBLE",
      "association_method": "CENTER_CONTAINMENT",
      "association_confidence": 0.92,
      "reason_code": "NEGATIVE_LABEL_DETECTED"
    }
  }
}
```

## 3. Trường bắt buộc

| Nhóm | Trường | Ý nghĩa |
|---|---|---|
| Version | `schema_version` | Cho phép nâng schema mà không làm log cũ mất nghĩa. |
| Run | `camera_id`, `run_id` | Tách camera và lần chạy. |
| Time | `frame_id`, `timestamp_ms` | Truy ngược đúng frame/timeline video. |
| Track | `track_id`, `track_status` | ID tạm thời và trạng thái tracker. |
| Person | `box`, `confidence`, `foot_point` | Tái sử dụng output detector/tracker và zone logic hiện tại. |
| Zone | `zone_ids` | Polygon đang chứa foot-point; rỗng nếu ở ngoài zone. |
| PPE | một record cho từng loại PPE được đánh giá | Chứa state, evidence, association và lý do. |

## 4. Enum cốt lõi

### PPE state

| Giá trị | Nghĩa |
|---|---|
| `WORN` | Có bằng chứng dương tính hợp lệ rằng worker đang mặc PPE. |
| `NOT_WORN` | Có nhãn âm rõ ràng như `no_helmet` được gán đúng owner và vùng cần kiểm tra nhìn thấy. |
| `UNKNOWN` | Không đủ bằng chứng để kết luận. Đây không phải vi phạm. |

Không có `CARRIED` trong core 1.0 vì 11 class hiện tại không dạy model phân biệt “đang cầm” với “đang mặc”.

### Visibility

```text
VISIBLE | PARTIAL | OUT_OF_FRAME | OCCLUDED | UNKNOWN
```

Trong phiên bản đầu, rule hình học chỉ có thể hỗ trợ chắc chắn `OUT_OF_FRAME/PARTIAL` từ box và biên ảnh. `OCCLUDED` là giá trị dự phòng; chỉ được phát khi một module sau có bằng chứng, không được đoán.

### Association method

```text
CENTER_CONTAINMENT | UNASSIGNED
```

Task 20 giữ đúng baseline hiện tại. Các giá trị như `GEOMETRY_MATCHING` hoặc `POSE_GUIDED` chỉ được thêm khi Task 24/25 thực sự triển khai và tăng `schema_version` phù hợp.

## 5. Mapping 11 class hiện tại

| Nhãn detector | PPE field | State có thể kết luận | Vùng kỳ vọng |
|---|---|---|---|
| `helmet` | `helmet` | `WORN` | `HEAD` |
| `no_helmet` | `helmet` | `NOT_WORN` | `HEAD` |
| `goggles` | `goggles` | `WORN` | `HEAD` |
| `no_goggle` | `goggles` | `NOT_WORN` | `HEAD` |
| `vest` | `vest` | `WORN` | `TORSO` |
| `gloves` | `gloves` | `WORN` | `HANDS` |
| `no_gloves` | `gloves` | `NOT_WORN` | `HANDS` |
| `boots` | `boots` | `WORN` | `FEET` |
| `no_boots` | `boots` | `NOT_WORN` | `FEET` |
| `Person` | không phải PPE | Tạo đầu vào cho tracker | `FULL_BODY` |
| `none` | không map | `UNKNOWN`/bỏ khỏi association | `UNKNOWN` |

Không có `no_vest`, vì vậy khi không detect `vest`, state đúng là `UNKNOWN`, không phải `NOT_WORN`.

`expected_region` chỉ mô tả nơi PPE được kỳ vọng xuất hiện. Nó không có nghĩa hệ thống đã chạy pose hoặc đã có keypoint.

## 6. Reason code

### Dùng được với pipeline/rule hiện tại

```text
POSITIVE_LABEL_DETECTED
NEGATIVE_LABEL_DETECTED
LOW_DETECTION_CONFIDENCE
NO_PPE_EVIDENCE
BODY_REGION_OUT_OF_FRAME
PERSON_TOO_SMALL
AMBIGUOUS_OWNER
TRACK_TEMPORARILY_LOST
CONFLICTING_EVIDENCE
```

### Dành chỗ cho module có bằng chứng sau này

```text
BODY_REGION_OCCLUDED
```

Quy tắc ưu tiên an toàn:

1. Track `LOST` -> `UNKNOWN/TRACK_TEMPORARILY_LOST`.
2. Vùng PPE ngoài ảnh hoặc person quá nhỏ -> `UNKNOWN`.
3. Có nhiều owner hợp lệ hoặc positive/negative evidence xung đột -> `UNKNOWN`.
4. Negative label hợp lệ -> `NOT_WORN`.
5. Positive label hợp lệ -> `WORN`.
6. Không có evidence -> `UNKNOWN`, trừ khi nghiên cứu sau chứng minh được một negative rule đáng tin cậy.

## 7. Evidence không có owner

Nếu PPE/no_PPE box không thể gán chắc chắn cho worker, không được tạo WorkerState giả hoặc WorkerEvent:

```json
{
  "schema_version": "1.0",
  "camera_id": "0003",
  "run_id": "run_20261009_001",
  "frame_id": 152,
  "detection_class": "no_helmet",
  "box": [700, 100, 750, 160],
  "confidence": 0.74,
  "reason_code": "NO_VALID_PERSON_OWNER"
}
```

Record này chỉ dùng để vẽ/debug và tính lỗi association về sau.

## 8. Điều kiện hợp lệ tối thiểu

- `track_id` bắt buộc nếu object được gọi là WorkerState.
- `timestamp_ms` không được giảm trong cùng một run/track.
- Box phải nằm theo thứ tự `[x1, y1, x2, y2]` và có diện tích dương.
- `NOT_WORN` phải có negative evidence tương ứng và reason code rõ.
- `UNKNOWN` không được mở một event vi phạm mới.
- Một PPE record chỉ mô tả một loại PPE; không gộp `no_helmet|no_gloves` thành một state.

## Kết luận bước 3

Schema này dùng trực tiếp các field đã có trong project, chỉ bổ sung identity, uncertainty và evidence có cấu trúc. Nó không buộc hệ thống thêm pose, ReID hoặc model mới để bắt đầu triển khai.
