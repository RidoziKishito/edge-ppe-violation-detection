# 05 - System-method matrix

| Component | Method | Status | Evidence still needed |
|---|---|---|---|
| Four-label PPE detection | YOLO26n DetectionHead | Implemented, model study in progress | Final checkpoint and full validation |
| Person detection | Separate lightweight Person detector | Implemented | Representative-video recall |
| Worker tracking | ByteTrack without ReID | Implemented | ID stability and runtime benchmark |
| PPE ownership | One-to-one center containment | Implemented | Failure review on overlap clips |
| Worker PPE state | Helmet/vest `WORN`, `NOT_WORN`, `UNKNOWN` | Implemented | Regression tests on selected videos |
| Zone reasoning | Foot-point inside warning/danger polygon | Implemented | Zone editor and saved-asset regression |
| Worker event | Dwell, cooldown, `START/UPDATE/END` | Implemented | Duplicate-event and alert-delay review |
| Evidence archive | CSV, snapshot, output video and run archive | Implemented | End-to-end run verification |
| Edge deployment | Batch-1 local pipeline, later TensorRT FP16 | Pending benchmark | FPS, P50/P95, RAM/VRAM and Jetson results |

## Core architecture

```text
PPE model + Person model
          -> ByteTrack
          -> center-containment association
          -> helmet/vest WorkerState
          -> polygon and WorkerEvent
          -> logger, recap and dashboard
```

The release does not depend on pose, ReID, visibility estimation, Metric-2D or dynamic risk.

