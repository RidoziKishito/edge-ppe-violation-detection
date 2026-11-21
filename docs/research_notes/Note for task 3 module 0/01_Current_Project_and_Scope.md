# 01 - Current project and scope

## Current pipeline

```text
PPE detector: helmet / no_helmet / vest / no_vest
Person detector: Person boxes
Person boxes -> ByteTrack -> track_id
PPE boxes -> center containment -> WorkerState
WorkerState + foot-point + polygon -> WorkerEvent
WorkerEvent -> CSV, snapshot, output video and dashboard
```

## Features retained from the original project

| Feature | Current use |
|---|---|
| YOLO inference | Retained with the four-label Dataset v2 scope |
| Warning and danger polygons | Retained as camera-specific spatial rules |
| Person foot-point | Determines whether a worker is inside a polygon |
| Temporal confirmation and cooldown | Applied per worker and PPE event |
| CSV, snapshot and output video | Retained with run, track and event fields |
| Local dashboard | Runs and reviews results without a cloud service |

## Current limitations

- Small helmet and vest boxes remain harder than medium and large objects.
- ByteTrack cannot preserve an ID when Person detection is absent longer than its buffer.
- PPE detections can flicker, so events require dwell time and cooldown.
- Overlapping person boxes can make owner assignment ambiguous; the current rule leaves that evidence unassigned.
- Edge performance still requires batch-1 end-to-end measurement on the target Jetson.

## Release scope

The release is a lightweight four-label PPE monitoring system. It includes detection, anonymous per-run tracking, polygon zones and worker-level events. Features requiring a new label taxonomy, keypoints, calibrated distance or worker-machine risk data are excluded.

