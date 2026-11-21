# 01 - Current system mapping

## Runtime flow

```text
Read frame
 -> detect Person with the person model
 -> detect four PPE labels with the PPE model
 -> update ByteTrack with Person boxes
 -> assign each PPE box to at most one tracked Person
 -> build helmet and vest WorkerState
 -> calculate foot-point and active polygons
 -> update WorkerEvent state machine
 -> render and save log, snapshot and output video
```

## Reused components

| Existing component | Current role |
|---|---|
| Polygon zone and foot-point | Spatial rule for each tracked worker |
| `NORMAL/WARNING/CRITICAL` | Event severity |
| Confirmation and cooldown | Prevent flickering and duplicate alerts |
| CSV and snapshot | Worker-event evidence |
| Dashboard run archive | Stores one run, model settings, output and logs |

## Changes introduced by Task 20

- Added `run_id`, `track_id`, `worker_key` and `event_id`.
- Changed temporal ownership from `zone_id` to worker and PPE type.
- Split helmet and vest into separate event streams.
- Added reason codes and structured PPE evidence.
- Kept backward-compatible logger fields for the dashboard.

The current contract reflects implemented behavior. It does not claim pose, visibility estimation or identity recognition.
