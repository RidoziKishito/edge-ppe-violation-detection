# 05 - Runtime integration and compatibility

## Component contract

| Component | Input | Output |
|---|---|---|
| Person detector | Frame | Person boxes and confidence |
| PPE detector | Frame | Four-label PPE boxes and confidence |
| PersonTracker | Person boxes | Active, lost and removed track IDs |
| Association | Tracks and PPE boxes | One owner or unassigned evidence |
| WorkerState builder | Tracks, PPE evidence and polygons | Helmet/vest state per worker |
| WorkerEvent engine | Worker observations | `START/UPDATE/END` events |
| Logger/dashboard | Events and rendered frames | CSV, snapshots, output video and recap |

## Logger compatibility

Legacy fields such as camera, frame, zone, alert level, violation, confidence, bounding box and snapshot path are retained. Structured fields append:

```text
schema_version, run_id, event_id, event_action, event_status,
track_id, worker_key, ppe_type, ppe_state, association_method,
association_confidence, visibility, reason_code, start_frame,
end_frame, duration_ms
```

## Implemented safeguards

- A PPE box is never assigned to two overlapping workers.
- `no_helmet` and `no_vest` create separate worker events.
- Lost and removed tracks have explicit event behavior.
- Starting another video creates a new run and tracker state.
- Dashboard counts event starts without counting every update or end as a new alert.
- The four-label reporting scope is shared by runtime, event filters and analytics.

Task 20 is complete at implementation and contract-test level. Remaining work is representative-video validation, parameter tuning and edge benchmarking in later tasks.
