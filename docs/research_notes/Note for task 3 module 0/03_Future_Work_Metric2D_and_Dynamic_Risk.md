# 03 - Future Work: Metric-2D and dynamic risk

## Trạng thái

**Future Work - không triển khai trong phạm vi hiện tại.**

Dynamic risk cần đồng thời:

- video có công nhân và máy móc;
- Track ID cho cả người và máy;
- camera calibration hoặc tọa độ mặt đất theo mét;
- vận tốc/quỹ đạo thực;
- nhãn near-miss, collision hoặc TTC để đánh giá.

Các nguồn đã kiểm tra chỉ đáp ứng từng phần:

| Nguồn | Có | Thiếu so với project |
|---|---|---|
| [CMOT](https://github.com/XZ-YAN/CMOT-Dataset) | Video, Track ID, người và nhiều loại máy | Tọa độ mét, vận tốc thật, TTC/near-miss ground truth |
| [PM-HMCW](https://github.com/dyxm/PM-HMCW) | Ảnh có 3D box và mức proximity | Video trajectory và TTC ground truth |
| [HARD-HAT](https://zenodo.org/records/19607695) | Robot-người, ROS logs, trajectory và distance | Không phải fixed-CCTV PPE; chỉ một người trong bối cảnh kiểm soát |

Ghép các nguồn trên không tạo thành một dataset thống nhất để train và đánh giá dynamic risk cho project này.

## Điều kiện để mở lại

Chỉ xem xét khi có một bộ video fixed-camera riêng, được hiệu chuẩn, có người và máy xuất hiện cùng lúc, Track ID, tọa độ/vận tốc theo thời gian và nhãn risk được kiểm tra. Khi chưa đáp ứng đủ, project tiếp tục dùng polygon zone hiện có.
