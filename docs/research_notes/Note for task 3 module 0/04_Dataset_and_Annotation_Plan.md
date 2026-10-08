# 04 - Dataset and annotation plan

## 1. Dữ liệu theo từng nhiệm vụ

Không merge phẳng mọi nguồn vì nhãn thiếu có thể bị hiểu sai thành background.

| Dataset | Vai trò |
|---|---|
| Dataset v1 | Train/benchmark detector 11 lớp sau khi audit |
| [Construction-PPE](https://docs.ultralytics.com/datasets/detect/construction-ppe/) | Đối chiếu taxonomy và dữ liệu bổ sung phù hợp |
| [SH17](https://github.com/ahmadmughees/SH17dataset) | Tham khảo PPE/body-part box; không tự động đổi `Shoes` thành boots hoặc `Glasses` thành goggles |
| [CMOT](https://github.com/XZ-YAN/CMOT-Dataset) | Benchmark tracking và helmet/no-helmet; không dùng làm multi-PPE association ground truth |
| `PPE-MOT-mini` tự tạo | Đánh giá Track ID, chủ sở hữu PPE, trạng thái và worker-level event |
| `robustness_v1` | Đánh giá small-object, low-light, motion blur và truncation; gồm corruption có kiểm soát và field subset thật |

CMOT đã được tải tại `D:/UTE/TLCN/Dataset/CMOT` với đủ 50 train, 10 validation và 40 test cùng annotation. Đây là bản lấy từ luồng preview chính thức của AliPan vì tải file gốc ẩn danh bị chặn. Khi chấm tracking phải đọc `DOWNLOAD_STATUS.md`: không dùng các sequence bị đổi FPS/frame (`train/0023`, `train/0031`, `train/0032`, `val/0028`) như ground truth frame-aligned; các sequence bị đổi độ phân giải phải scale box đúng trước khi đánh giá.

## 2. Audit Dataset v1

1. Lập manifest nguồn nếu còn truy vết được.
2. Dò ảnh trùng và gần trùng.
3. Chia theo nguồn/site thay vì chia ngẫu nhiên từng ảnh.
4. Kiểm tra lớp hiếm, đặc biệt `no_boots` và việc thiếu `no_vest`.
5. Làm rõ hoặc bỏ lớp `none` khỏi rule mới.
6. Giữ nhãn gốc; mapping sang worker state ở tầng association.

Dataset v1 chỉ có box rời, không có `track_id`, `owner_track_id`, visibility hoặc trạng thái theo thời gian.

## 3. Tạo PPE-MOT-mini

Quy mô khả thi ban đầu: 10-20 clip, mỗi clip 5-15 giây, 1-4 người. Có thể annotate ở 10-15 FPS; chỉ mở rộng khi kết quả cho thấy association còn lỗi.

Cảnh cần có:

- mặc và thiếu helmet/vest;
- đội và tháo helmet; cảnh cầm helmet chỉ thêm nếu muốn kiểm tra riêng `CARRIED`;
- che khuất tự nhiên và người đi ra/vào khung hình;
- người/PPE nhỏ ở xa camera;
- ảnh tối và motion blur ở nhiều mức;
- đầu, tay hoặc chân bị cắt khỏi ảnh để kiểm tra `UNKNOWN`.

Helmet và vest là bắt buộc. Gloves, boots và goggles chỉ thêm khi hình ảnh đủ rõ.

## 4. Auto-label và duyệt

```text
Video thật
 -> YOLO hiện tại: person/PPE boxes
 -> ByteTrack: track ID ban đầu
 -> CVAT: sửa box, track ID, owner và state interval
 -> người duyệt các đoạn khó
```

Auto-label chỉ tạo nhãn ban đầu. `owner_track_id`, trường hợp che khuất và chuyển trạng thái phải được con người kiểm tra.

## 5. Annotation cần lưu

### Detection

```text
class_id x_center y_center width height
```

### Tracking

```text
frame, track_id, x, y, width, height, confidence, class, visibility
```

### Relation và trạng thái

```json
{
  "video_id": "V01",
  "track_id": 3,
  "ppe_class": "helmet",
  "ppe_box_id": 27,
  "body_region": "head",
  "state": "WORN",
  "visibility": "visible",
  "condition": ["small", "low_light"],
  "owner_verified": true,
  "start_frame": 120,
  "end_frame": 188
}
```

## 6. Quy tắc trạng thái

- `WORN`: PPE ở đúng vùng cơ thể.
- `NOT_WORN`: vùng cần kiểm tra nhìn rõ và xác nhận không có PPE.
- `CARRIED`: helmet gần tay và không nằm ở đầu; chỉ dùng khi clip đã ghi nhãn tình huống này.
- `UNKNOWN`: bị che, ngoài khung, quá mờ hoặc gán chủ sở hữu không chắc chắn.
- `NOT_ANNOTATED`: nguồn không gắn nhãn PPE đó; không được đổi thành `NOT_WORN`.

Vì Dataset v1 thiếu `no_vest`, chỉ kết luận `NOT_WORN` cho vest nếu video cầu nối có nhãn xác nhận vùng thân nhìn rõ; nếu không thì dùng `UNKNOWN`.

## 7. Tạo robustness_v1

1. Giữ một bản clean validation/test bất biến.
2. Từ bản sao có nhãn, tạo low-light và motion-blur theo nhiều severity; box giữ nguyên và lưu seed/tham số.
3. Tạo train augmentation riêng bằng gamma/brightness/contrast/noise, motion blur và random crop; không đưa corrupted final test trở lại train.
4. Thu một field subset nhỏ có cảnh thật: xa camera, tối, mờ chuyển động và người bị cắt biên.
5. Ghi `condition`, `severity`, kích thước bbox và visibility để báo cáo theo từng lát dữ liệu.

SAHI và person-crop không cần nhãn mới để chạy thử, nhưng phải đánh giá trên cùng tập có nhiều small boxes. Visibility gate cần nhãn `visible/partially_visible/out_of_frame/occluded` cho vùng PPE liên quan.

## 8. Chia tập và kiểm soát chất lượng

- Chia theo video, người và camera/site; không chia frame ngẫu nhiên.
- Test chỉ dùng video thật chưa dùng để tuning.
- Hai người duyệt chéo các cảnh association khó.
- Lưu nguồn nhãn, phiên bản model auto-label và trạng thái human review.
- Ảnh sinh chỉ hỗ trợ train trường hợp hiếm; không dùng trong test, HOTA hoặc event evaluation.
