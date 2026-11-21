# 02 - Tracking and PPE association

## Worker tracking

ByteTrack receives only Person boxes and returns temporary IDs for one camera and one run.

```text
Person detector -> ByteTrack -> track_id
PPE detector ----------------> association
```

The current adapter uses high/low detection thresholds, a track buffer and IoU matching. It does not use ReID and does not identify a real person. The tracker resets when a new run or input source starts.

## PPE association

For each PPE box:

1. Calculate its center.
2. Find the tracked person boxes containing that center.
3. Assign it only when exactly one owner exists.
4. Leave it unassigned when there is no owner or more than one possible owner.

This keeps the original center-containment idea but prevents the same PPE box from being counted for two workers.

## Worker PPE state

| Evidence | State |
|---|---|
| `helmet` or `vest` | `WORN` |
| `no_helmet` or `no_vest` | `NOT_WORN` |
| No evidence | `UNKNOWN` |
| Positive and negative evidence conflict | `UNKNOWN` |
| Track temporarily lost | `UNKNOWN` at event-processing level |

The current runtime does not claim to detect occlusion or body-part visibility. `UNKNOWN` means the available detection evidence is insufficient.

## Evaluation kept in scope

- ID switches and track fragmentation on representative videos.
- Track recovery during short occlusion.
- Unassigned and ambiguous PPE evidence.
- Duplicate event rate and alert stability.
- Batch-1 FPS, P50/P95 latency and memory.

HOTA and IDF1 are optional only when compatible person-track ground truth is available. They are not required for the four-label detector.

