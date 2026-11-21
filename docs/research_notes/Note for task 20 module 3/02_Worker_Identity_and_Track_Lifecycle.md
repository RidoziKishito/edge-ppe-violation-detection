# 02 - Worker identity and track lifecycle

## Identity

```text
worker_key = camera_id + run_id + track_id
```

`track_id` is a temporary runtime identifier. It is not an employee ID and is not reused across runs as a real-world identity.

## Tracker input and output

ByteTrack receives only Person boxes:

```json
{
  "box": [410, 120, 620, 690],
  "confidence": 0.91,
  "class_name": "Person"
}
```

The normalized output adds `track_id` and `track_status=CONFIRMED`. PPE boxes remain outside the tracker.

## Runtime lifecycle

| Condition | Behavior |
|---|---|
| Person matched | Return active confirmed track |
| Person missing briefly | Track ID is kept in ByteTrack's lost buffer |
| Person detected again within buffer | Existing track may be recovered |
| Buffer expires | Track becomes removed and active events end with `TRACK_ENDED` |
| New run or input source | Tracker state resets |

ByteTrack cannot guarantee the same ID after a long disappearance. ReID is intentionally excluded to keep the pipeline lightweight and anonymous.
