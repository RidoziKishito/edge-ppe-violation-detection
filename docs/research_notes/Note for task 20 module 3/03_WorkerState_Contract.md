# 03 - WorkerState contract

`WorkerState` describes one tracked worker at one inference frame.

```json
{
  "schema_version": "1.0",
  "worker_key": "0003/run_001/7",
  "camera_id": "0003",
  "run_id": "run_001",
  "frame_id": 152,
  "timestamp_ms": 5066,
  "track_id": 7,
  "track_status": "CONFIRMED",
  "person": {
    "box": [412, 121, 621, 691],
    "confidence": 0.90,
    "foot_point": [516, 691]
  },
  "zone_ids": ["Z01"],
  "ppe": {
    "helmet": {
      "state": "NOT_WORN",
      "evidence_class": "no_helmet",
      "confidence": 0.88,
      "association_method": "CENTER_CONTAINMENT",
      "reason_code": "NEGATIVE_LABEL_DETECTED"
    },
    "vest": {
      "state": "UNKNOWN",
      "evidence_class": null,
      "confidence": 0.0,
      "association_method": "UNASSIGNED",
      "reason_code": "NO_PPE_EVIDENCE"
    }
  }
}
```

## Label mapping

| Detector label | PPE requirement | State |
|---|---|---|
| `helmet` | Helmet | `WORN` |
| `no_helmet` | Helmet | `NOT_WORN` |
| `vest` | Safety vest | `WORN` |
| `no_vest` | Safety vest | `NOT_WORN` |

When positive and negative labels for the same PPE are both assigned, the state is `UNKNOWN/CONFLICTING_EVIDENCE`. Missing evidence is also `UNKNOWN`; it is not automatically a violation.

The `visibility` field remains in the logger contract for compatibility, but the current implementation only records `VISIBLE` when evidence exists and `UNKNOWN` otherwise. It does not estimate occlusion.
