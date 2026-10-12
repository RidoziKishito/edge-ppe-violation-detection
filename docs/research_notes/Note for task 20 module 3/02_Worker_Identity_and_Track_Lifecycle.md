# 02 - Danh tính tạm thời và vòng đời track

## 1. ByteTrack được tham khảo ở phần nào

ByteTrack nhận danh sách **Person box** theo từng frame và nối chúng thành các quỹ đạo. Kết quả cần lấy từ tracker chỉ gồm:

```text
track_id + person_box + track_confidence + track_status
```

ByteTrack không biết helmet, gloves, boots hay vi phạm. PPE boxes vẫn do YOLO hiện tại phát hiện và được rule association gán cho person track sau đó.

```text
Person detections -> ByteTrack -> WorkerTrack(track_id)
PPE detections ----------------> association với WorkerTrack
```

Đây là thiết kế interface cho Task 22, không phải tích hợp ByteTrack trong Task 20.

## 2. Khóa định danh worker

```text
worker_key = camera_id + run_id + track_id
```

Giải thích tự nhiên:

- `track_id=7` không có nghĩa là “công nhân số 7” ngoài đời.
- ID này chỉ dùng để nối các frame của một camera trong đúng một lần chạy.
- Camera khác hoặc video khác có thể cùng sinh `track_id=7` nhưng vẫn là hai worker key khác nhau.
- Không lưu tên, khuôn mặt, số nhân viên hoặc vector ReID.

Ví dụ:

```text
cam_01 / run_20261009_001 / track_7
```

## 3. Contract vào/ra của tracker

### Input

Chỉ chuyển Person detection vào tracker:

```json
{
  "frame_id": 152,
  "timestamp_ms": 5066,
  "box": [410, 120, 620, 690],
  "confidence": 0.91,
  "class_name": "Person"
}
```

### Output chuẩn hóa

```json
{
  "camera_id": "0003",
  "run_id": "run_20261009_001",
  "frame_id": 152,
  "timestamp_ms": 5066,
  "track_id": 7,
  "track_status": "CONFIRMED",
  "box": [412, 121, 621, 691],
  "confidence": 0.90
}
```

PPE detections không đi qua tracker và không được cấp track riêng trong core.

## 4. Bốn trạng thái track

| Trạng thái | Ý nghĩa | Quy tắc đối với PPE event |
|---|---|---|
| `TENTATIVE` | Track mới, chưa xuất hiện đủ ổn định. | Có thể thu evidence để debug nhưng chưa mở event chắc chắn. |
| `CONFIRMED` | Tracker đã xác nhận đây là một quỹ đạo ổn định. | Được tạo/cập nhật WorkerState và WorkerEvent. |
| `LOST` | Tạm mất person detection, thường do che ngắn hoặc detection hụt. | Giữ event hiện có trong grace window; PPE chuyển `UNKNOWN`, không tự kết luận đã hết vi phạm. |
| `REMOVED` | Tracker kết thúc quỹ đạo sau khi quá thời gian chờ. | Đóng event còn active với `reason_code=TRACK_ENDED`. |

Chuyển trạng thái hợp lệ:

```text
TENTATIVE -> CONFIRMED -> LOST -> CONFIRMED
     |            |        |
     +----------> REMOVED <-+
```

Không cho track đã `REMOVED` sống lại. Nếu người xuất hiện lại sau khi track bị xóa, tracker tạo `track_id` mới.

## 5. Quy tắc reset và mất dấu

Tracker phải reset khi:

- chọn video input mới;
- bắt đầu `run_id` mới;
- đổi camera;
- camera reconnect theo một session mới;
- người dùng dừng và khởi động lại theo chế độ tạo run mới.

Khi track chỉ `LOST` vài frame:

1. không gán PPE box mới cho box dự đoán nếu association không đủ chắc chắn;
2. không tạo event mới;
3. không kết luận `WORN` hay `NOT_WORN`;
4. giữ event active đến khi track quay lại hoặc bị `REMOVED`;
5. ghi `TRACK_TEMPORARILY_LOST` nếu cần giải thích trạng thái `UNKNOWN`.

## 6. Ràng buộc Edge AI

- Chỉ track `Person`, không track từng PPE box.
- Không bật ReID trong core.
- Mỗi camera có đúng một tracker state độc lập.
- Trạng thái track lưu trong RAM và được xóa khi run kết thúc.
- Chỉ log transition quan trọng, không ghi toàn bộ tracker state ở mọi display frame.
- Đánh giá latency của tracker riêng và end-to-end ở Task 23/Module Edge; Task 20 chưa đưa ra lời hứa FPS.

## Kết luận bước 2

ByteTrack là nguồn cấp ID tạm thời, không phải model nhận diện PPE. Contract này tạo ranh giới rõ: tracker chịu trách nhiệm “đây có còn là cùng person không”, còn association và WorkerState chịu trách nhiệm “PPE nào đang thuộc person đó”.
