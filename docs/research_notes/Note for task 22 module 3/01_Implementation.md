# ByteTrack implementation

## Runtime flow

```text
Video frame
  → Person detector
  → ByteTrack
  → anonymous track_id
  → WorkerState and PPE association
  → WorkerEvent and logger
```

ByteTrack is not another PPE model. It receives Person boxes produced by YOLO and links boxes between frames by their position, overlap, confidence and short-term motion.

## Input and output contract

Input to the tracker:

- Person bounding box `[x1, y1, x2, y2]`.
- Person confidence.
- Frame image and frame rate.

Output from the tracker:

- active Person box and confidence;
- anonymous integer `track_id`;
- `lost_track_ids` for tracks retained temporarily without a current detection;
- `removed_track_ids` for tracks that exceeded the retention window.

Only Person detections are tracked. PPE boxes remain detector evidence and are associated with the active worker state afterward.

## Current configuration

| Parameter | Current value | Meaning |
|---|---:|---|
| `track_high_thresh` | 0.25 | High-confidence Person detections used in the first association pass |
| `track_low_thresh` | 0.10 | Lower-confidence detections that may recover an existing track |
| `new_track_thresh` | 0.25 | Minimum confidence for creating a new track |
| `track_buffer` | 60 updates | How long a temporarily lost track is retained |
| `match_thresh` | 0.80 | Matching tolerance used by ByteTrack |
| `fuse_score` | `False` | Prevents weak boxes from being penalised again during matching |

These are implementation defaults, not yet claimed as the best settings for every camera.

## Integration decisions

1. The PPE model remains responsible for the four PPE labels.
2. A separate Person detector can be configured for stable tracking.
3. The Person inference confidence is allowed to reach the tracker low threshold so ByteTrack can use its second association pass.
4. Tracker state is reset for each new run, so IDs are local to that run.
5. No ReID model is added, preserving the lightweight Edge-AI scope.

## Expected behaviour

- A short confidence drop does not immediately create a new ID if ByteTrack can match the weaker Person box to an existing track.
- A temporarily missing worker enters the lost state but is not immediately treated as a completed track.
- A worker missing longer than the buffer is removed; a later reappearance may receive a new ID.

