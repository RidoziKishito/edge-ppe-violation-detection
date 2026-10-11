# Task 20 - Worker-centric runtime state and PPE event lifecycle

> Module: 3 - Tracking & Worker-PPE Association
> Phạm vi: thiết kế contract và tích hợp runtime nhẹ; chưa tạo dataset video ground truth và chưa huấn luyện lại model PPE.

## Mục tiêu

Project hiện tại phát hiện `Person`, PPE và `no_PPE` theo từng frame, sau đó gom cảnh báo theo `zone_id`. Task 20 thiết kế lớp dữ liệu trung gian để các task sau có thể trả lời rõ:

- công nhân nào đang được theo dõi;
- PPE nào đã được gán cho công nhân đó;
- hệ thống thấy `WORN`, `NOT_WORN` hay chưa đủ bằng chứng (`UNKNOWN`);
- một vi phạm bắt đầu, thay đổi và kết thúc lúc nào;
- log và dashboard truy ngược được về đúng camera, lần chạy, `track_id` và bằng chứng.

## Năm phần thiết kế

1. [Đối chiếu pipeline cũ và xác định phần giữ lại](01_Current_System_Mapping.md)
2. [Định nghĩa danh tính tạm thời và vòng đời track](02_Worker_Identity_and_Track_Lifecycle.md)
3. [Thiết kế WorkerState](03_WorkerState_Contract.md)
4. [Thiết kế WorkerEvent và vòng đời sự kiện](04_WorkerEvent_Lifecycle.md)
5. [Thiết kế điểm nối với rule engine, logger và dashboard](05_Legacy_Integration_Contract.md)

## Kiến trúc đã chốt

```text
Video/camera
   |
   +--> YOLO11n COCO: Person boxes --> ByteTrack
   |                                      |
   +--> YOLO PPE hiện tại: PPE/no_PPE     | track_id
                         |                |
                         +--------+-------+
                                  v
                 tâm PPE trong person box
                                  |
                                  v
                         WorkerState/frame
                                  |
                   foot-point + polygon zone
                                  |
                                  v
                    WorkerEvent/worker/PPE
                                  |
                                  v
                  Logger + archive + dashboard
```

## Quyết định phạm vi

- Giữ YOLO, 11 class hiện tại, luật tâm box, foot-point, polygon zone, mức `NORMAL/WARNING/CRITICAL`, snapshot, video đầu ra và run archive.
- ByteTrack chỉ cấp `track_id` cho `Person`; nó không nhận biết PPE và không nhận diện danh tính thật.
- Không đưa pose, ReID, Hungarian matching, homography hay dynamic risk vào Task 20.
- Không đưa `CARRIED` vào core vì model/dataset hiện tại chưa có nhãn ổn định cho trạng thái cầm PPE nhưng không mặc.
- `UNKNOWN` khác `NOT_WORN`: không nhìn thấy hoặc không đủ bằng chứng không được xem là vi phạm.
- `track_id` chỉ có ý nghĩa trong một `camera_id` và một `run_id`; đổi video phải reset tracker.

## Nguồn tham khảo chính

- [ByteTrack - ECCV 2022](https://arxiv.org/abs/2110.06864): tham khảo cách tracker duy trì ID từ person detections, không dùng làm schema PPE.
- [HOTA - IJCV](https://www.graphics.rwth-aachen.de/publication/00207/): tham khảo cách tách chất lượng detection và association khi đánh giá tracking ở Task 23.
- [TCSS-Net - Frontiers 2026](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2026.1878141/full): tham khảo cách biểu diễn trạng thái không chắc chắn/không xác định; không sao chép toàn bộ kiến trúc.
- [Pose-guided PPE anchoring - Automation in Construction](https://www.sciencedirect.com/science/article/pii/S092658052100279X): chỉ tham khảo khái niệm PPE có vùng cơ thể kỳ vọng; Task 20 không chạy pose estimator.

## Đầu ra của Task 20

Năm tài liệu này chốt schema, enum, reason code, event identity và điểm nối với hệ thống cũ. Task 21 mới bắt đầu xây dựng video ground truth.

## Trạng thái triển khai - 10/10/2026

Contract nhẹ đã được đưa vào runtime mà không train lại detector:

- [`person_tracker.py`](../../../edge-pipeline/person_tracker.py): adapter ByteTrack chỉ nhận Person detections và trả `track_id`, lost/removed IDs.
- [`worker_state.py`](../../../edge-pipeline/worker_state.py): tạo WorkerState, ánh xạ 11 class sang `WORN/NOT_WORN/UNKNOWN` và sinh observation theo worker/PPE.
- [`pipeline_control.py`](../../../edge-pipeline/pipeline_control.py): `WorkerEventEngine` tạo `START/UPDATE/END`, dwell time, cooldown và xử lý LOST/REMOVED/UNKNOWN.
- [`logger.py`](../../../edge-pipeline/logger.py): giữ chín cột CSV cũ và bổ sung run/event/track/PPE/reason fields.
- [`edge_infer.py`](../../../edge-pipeline/edge_infer.py): nối YOLO -> ByteTrack -> WorkerState -> WorkerEvent -> logger.
- Runtime dùng hai detector: YOLO11n COCO chỉ lấy class `Person`; model PPE cũ bỏ qua class `Person` yếu và chỉ cung cấp bằng chứng PPE/no_PPE. Không cần gộp hoặc train lại hai dataset.
- Khung hình đầu ra hiển thị `track_id`, số vi phạm, số PPE chưa đủ bằng chứng và owner `ID` trên từng box PPE đã gán được.
- Dashboard và CLI truyền `run_id`; dashboard mặc định chỉ đếm `START` để các row `UPDATE/END` không làm sai số lượng cảnh báo.

Contract tests hiện bao phủ hai worker trong cùng zone, track mất/tái xuất hiện, track kết thúc, PPE trở lại `WORN`, `UNKNOWN` không đóng event, nhãn xung đột, `no_vest` và PPE không có owner. Việc đo HOTA/IDF1, tune ByteTrack và xác nhận trên video ground truth vẫn thuộc Task 21-23.
