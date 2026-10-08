# Task 3 - Review robust PPE detection, worker tracking and worker-PPE association

> Cập nhật: 07/10/2026  
> Phạm vi đã chốt: tăng độ bền của detector trong điều kiện camera xấu, tracking công nhân, gán PPE theo `track_id` và tạo sự kiện vi phạm theo từng công nhân.

## Kết luận

1. Giữ detector PPE, polygon zone, foot-point, temporal smoothing, logger, dashboard và benchmark edge của project cũ.
2. Thêm ByteTrack cho **Person** để giữ `track_id` qua nhiều frame; không train tracker mới.
3. Association core giữ rule tâm PPE nằm trong person box, sau đó ổn định kết quả theo `track_id`. Với góc camera mục tiêu, đây là baseline hợp lý và không cần pose/Hungarian trong critical path.
4. Bổ sung nhánh robustness: P2 thuộc Module 1; SAHI/person-crop là candidate inference cho vật thể nhỏ; low-light/motion-blur augmentation tăng độ bền; visibility gate trả `UNKNOWN` khi vùng cần kiểm tra không nhìn thấy.
5. Tạo worker state/event theo track; chỉ công bố các state có ground truth. Không mặc định hứa hẹn `CARRIED` nếu chưa có clip được gán nhãn cho tình huống này.
6. Metric-2D, machine tracking, TTC và dynamic risk là **Future Work** vì chưa có dataset/video ground truth phù hợp.
7. Giữ giá trị Edge AI bằng benchmark batch-1 end-to-end trên thiết bị mục tiêu. Con số 131.4 FPS batch 8 cũ không đại diện cho tốc độ camera đơn hay toàn pipeline.
8. ByteTrack core không dùng ReID và chỉ cấp ID tạm thời theo camera/run; không biến hệ thống thành nhận diện danh tính.

## Kiến trúc core

```text
Camera/video
    |
    v
Quality gate: brightness / blur / frame boundary
    |
    +--> conditional enhancement
    +--> SAHI hoặc person-crop khi đối tượng nhỏ
    v
YOLO Person + PPE/no_PPE
    |-- Person boxes --> ByteTrack --> WorkerTrack(track_id) ------+
    +-- PPE/no_PPE boxes ------------------------------------------+
                                                                  v
                                               center containment
                                                                  |
                                                    visibility gate
                                                                  |
                                               PPE state + temporal event
                                                                  |
                                             polygon zone + logger/dashboard
```

## Tài liệu

- [01_Project_Baseline_and_Scope.md](01_Project_Baseline_and_Scope.md): phần cũ nên giữ, vấn đề và phạm vi cuối.
- [02_Tracking_and_Worker_PPE_Association.md](02_Tracking_and_Worker_PPE_Association.md): tracking, association, trạng thái và metric.
- [03_Future_Work_Metric2D_and_Dynamic_Risk.md](03_Future_Work_Metric2D_and_Dynamic_Risk.md): Metric-2D, machine tracking, TTC và dynamic risk được đánh dấu Future Work trong cùng một tài liệu.
- [04_Dataset_and_Annotation_Plan.md](04_Dataset_and_Annotation_Plan.md): dataset cầu nối và quy trình gán nhãn.
- [05_System_Method_Matrix_and_Architecture.md](05_System_Method_Matrix_and_Architecture.md): ma trận phương pháp, thí nghiệm và đầu ra.
- [06_Robust_PPE_Detection_Under_Adverse_Conditions.md](06_Robust_PPE_Detection_Under_Adverse_Conditions.md): vật thể nhỏ, ảnh tối, motion blur, truncation và visibility-aware inference.

## Thứ tự thực hiện

```text
Baseline và error analysis theo kích thước/điều kiện
 -> P2 baseline; thử SAHI/person-crop có kiểm soát
 -> low-light/motion-blur augmentation và quality gate
 -> ByteTrack
 -> center-containment association
 -> visibility-aware state
 -> per-worker temporal event
 -> edge benchmark và tích hợp dashboard
 -> pose/matching chỉ ghi Future Work nếu xuất hiện lỗi thực tế chưa giải quyết được
 -> Metric-2D/TTC/dynamic risk tiếp tục Future Work, không đi vào release core
```
