# 02 - Tracking and worker-PPE association

## 1. Worker tracking

[ByteTrack](https://github.com/FoundationVision/ByteTrack) nối person box giữa các frame và tận dụng cả detection confidence thấp để cứu track bị che ngắn. Trong project này chỉ đưa lớp `Person` vào tracker; PPE box không được cấp worker ID độc lập.

```text
YOLO chạy một lần
├── Person detections -> ByteTrack -> track_id
└── PPE detections ----------------> association
```

Mỗi camera cần một tracker state riêng và phải reset khi đổi video, camera reconnect hoặc bắt đầu run mới. Baseline tracking phải dùng `inference_interval=1`; không được giữ nguyên box cache qua nhiều frame rồi xem đó là tracking.

## 2. Metric tracking

- **HOTA:** metric chính, cân bằng detection và association.
- **DetA:** chất lượng phát hiện đối tượng.
- **AssA:** chất lượng giữ đúng quan hệ ID.
- **IDF1:** tỷ lệ detection được gán đúng danh tính trên quỹ đạo.
- **IDSW:** số lần một người bị đổi ID.
- **Frag:** số lần quỹ đạo bị đứt.
- **FPS/P50/P95 latency:** chi phí chạy trên edge.

Dùng [TrackEval](https://github.com/JonathonLuiten/TrackEval); HOTA được mô tả trong [bài báo gốc](https://arxiv.org/abs/2009.07736).

## 3. Association core và phạm vi đã chốt

### Core - tâm PPE nằm trong person box

PPE được gán cho người khi tâm PPE nằm trong person box. Đây là logic của project cũ, phù hợp với góc camera đặt cao và video mục tiêu; giữ làm phương pháp chính thay vì tự động bổ sung pose hoặc Hungarian.

Sau khi gán, kết quả được nối với `track_id` và ổn định qua nhiều frame. Confidence thấp, vùng cần kiểm tra không nhìn thấy hoặc frame quá mờ thì trả `UNKNOWN`; không ép kết luận vi phạm.

### Visibility gate không phải pose estimation

Vùng đầu/thân/tay/chân chỉ được ước lượng theo tỷ lệ person box và biên ảnh để xác định vùng đó có nhìn thấy hay không. Mục đích là tránh kết luận sai khi đầu hoặc chân ngoài khung, không phải học lại quan hệ PPE-keypoint.

Ví dụ:

- person box chạm cạnh trên và vùng đầu không hiện đầy đủ: helmet state là `UNKNOWN`;
- person box chạm cạnh dưới và vùng chân không hiện đầy đủ: boots state là `UNKNOWN`;
- ảnh mặt/tay quá nhỏ hoặc quá mờ: goggles/gloves state là `UNKNOWN`.

Pose-guided association và one-to-one matching không nằm trong core. Chỉ mở lại như Future Work khi failure analysis trên video thật chứng minh center containment gây lỗi có hệ thống mà visibility/temporal logic không giải quyết được.

TCSS-Net chỉ được dùng để tham khảo ý tưởng `occluded/uncertain/unknown`; không tái tạo pose estimator, GNN hoặc uncertainty head.

## 4. Quy tắc gán PPE cho Track ID

Mỗi PPE-worker relation lưu:

1. PPE có nằm trong person box hay không.
2. Confidence của Person và PPE.
3. Visibility của vùng cần kiểm tra.
4. Quan hệ của cùng `track_id` ở các frame trước.

Nếu vùng cần kiểm tra không nhìn thấy hoặc bằng chứng không đủ, kết quả là `UNKNOWN`. Không thêm matching phức tạp nếu chưa có failure case định lượng.

## 5. Mapping nhãn cũ sang worker state

| Detection cũ | Điều kiện vùng | Worker state |
|---|---|---|
| `helmet` | head region nhìn thấy | `helmet=WORN` |
| `helmet` | không nằm ở head region | không tự kết luận `CARRIED`; chỉ dùng khi có ground truth riêng |
| `no_helmet` | head region nhìn thấy | `helmet=NOT_WORN` |
| `vest` | torso nhìn thấy | `vest=WORN` |
| `goggles/no_goggle` | face nhìn thấy và đủ rõ | `WORN/NOT_WORN` |
| `gloves/no_gloves` | hand nhìn thấy và đủ rõ | `WORN/NOT_WORN` |
| `boots/no_boots` | foot nhìn thấy và đủ rõ | `WORN/NOT_WORN` |
| body region bị che hoặc confidence thấp | bất kỳ | `UNKNOWN` |
| `none` | không có semantic mapping tin cậy | bỏ khỏi association |

Dataset v1 thiếu `no_vest`, nên không được kết luận `vest=NOT_WORN` chỉ từ một frame không detect vest. Cần torso nhìn rõ, nhiều frame liên tiếp và ground truth từ video cầu nối hoặc dữ liệu `NoVest` bổ sung.

## 6. Temporal worker-level event

Lưu state theo khóa:

```text
(camera_id, track_id, ppe_type)
```

Chỉ mở event khi vi phạm tồn tại đủ số frame/thời gian; đóng event khi state trở lại `WORN` ổn định. `UNKNOWN` tạm thời giữ event nhưng không tạo vi phạm mới. Logger nên bổ sung:

```text
track_id, ppe_type, ppe_state, start_frame, end_frame,
duration_ms, association_score, body_region, visibility
```

## 7. Hoàn thành khi

- Có output MOT và metric HOTA/IDF1/IDSW.
- Có baseline center containment + visibility gate trên cùng video.
- Pose/one-to-one không nằm trong tiêu chí hoàn thành.
- Báo cáo owner accuracy/false assignment rate cho helmet và vest.
- Có event-level precision, recall, F1 và onset delay.
- Gloves/boots/goggles được ghi rõ là detection-only hoặc thử nghiệm, không gộp vào kết luận chính.
