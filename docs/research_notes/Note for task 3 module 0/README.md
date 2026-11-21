# Task 3 - Review Edge-AI PPE detection, tracking and event scope

> Trạng thái: Done
> Phạm vi hiện tại: bốn nhãn `helmet`, `no_helmet`, `vest`, `no_vest`.

## Kết luận đã chốt

1. Dataset v2 và detector mới chỉ tập trung helmet và safety vest. Bộ 11 nhãn cũ không còn là phạm vi release.
2. DetectionHead là kiến trúc detector chính vì cải thiện nhẹ so với Original mà vẫn đủ nhỏ cho Edge AI.
3. Person được phát hiện bằng detector riêng và đưa vào ByteTrack. PPE không được track độc lập.
4. PPE được gán cho worker bằng tâm box nằm trong đúng một person box. Trường hợp không có owner hoặc có nhiều owner được để unassigned.
5. Worker state chỉ có hai yêu cầu an toàn: helmet và vest, với `WORN`, `NOT_WORN`, `UNKNOWN`.
6. Polygon zone, foot-point, event log, snapshot, output video và dashboard được giữ lại.
7. CMOT chỉ dùng làm video demo/stress test tracking. Không dùng để train detector bốn nhãn và không tạo PPE-MOT-mini trong scope hiện tại.

## Không còn nằm trong scope

- Pose estimation, keypoint, Hungarian matching và ReID.
- Visibility/occlusion model hoặc suy luận theo vùng đầu, tay, chân.
- SAHI và person-crop ở runtime khi chưa có kết quả accuracy-latency đủ tốt.
- Pipeline riêng cho low-light, mưa, deblur hoặc super-resolution.
- Homography, Metric-2D, máy móc, TTC và dynamic risk.

## Tài liệu

- [01_Current_Project_and_Scope.md](01_Current_Project_and_Scope.md)
- [02_Tracking_and_Association.md](02_Tracking_and_Association.md)
- [03_Data_and_Evaluation_Scope.md](03_Data_and_Evaluation_Scope.md)
- [04_Model_and_Small_Object_Study.md](04_Model_and_Small_Object_Study.md)
- [05_System_Method_Matrix.md](05_System_Method_Matrix.md)
