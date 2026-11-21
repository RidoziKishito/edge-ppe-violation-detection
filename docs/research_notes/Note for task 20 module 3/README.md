# Task 20 - Four-label worker state and PPE event contract

> Trạng thái: Done
> Phạm vi: contract đã được tích hợp vào runtime, không chỉ dừng ở thiết kế.

## Current architecture

```text
Person detector -> ByteTrack ---------------------+
                                                   v
Four-label PPE detector -> center containment -> WorkerState
                                                   |
                                      foot-point + polygon
                                                   v
                                             WorkerEvent
                                                   |
                                  CSV + snapshot + dashboard
```

## Decisions

- Worker IDs are anonymous and valid only inside one `camera_id + run_id`.
- WorkerState contains only helmet and vest requirements.
- `UNKNOWN` represents missing or conflicting evidence. The current version does not estimate body-part visibility or occlusion.
- Events are separated by worker and PPE type and emit `START`, `UPDATE` and `END`.
- Pose, ReID, Hungarian matching, Metric-2D and dynamic risk are outside Task 20.

## Documents

1. [01_Current_System_Mapping.md](01_Current_System_Mapping.md)
2. [02_Worker_Identity_and_Track_Lifecycle.md](02_Worker_Identity_and_Track_Lifecycle.md)
3. [03_WorkerState_Contract.md](03_WorkerState_Contract.md)
4. [04_WorkerEvent_Lifecycle.md](04_WorkerEvent_Lifecycle.md)
5. [05_Legacy_Integration_Contract.md](05_Legacy_Integration_Contract.md)

## Implemented files

- `edge-pipeline/person_tracker.py`
- `edge-pipeline/worker_state.py`
- `edge-pipeline/pipeline_control.py`
- `edge-pipeline/logger.py`
- `edge-pipeline/edge_infer.py`
- `dashboard/workflow.py`
- `dashboard/app.py`
