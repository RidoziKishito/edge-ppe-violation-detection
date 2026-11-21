# 04 - WorkerEvent lifecycle

## Event identity

```text
event_key = camera_id + run_id + track_id + ppe_type + violation_type
```

Helmet and vest violations for the same worker are separate events. Two workers in the same polygon are also separate.

## Internal state and emitted actions

```text
IDLE -> CANDIDATE -> ACTIVE -> COOLDOWN -> IDLE
```

```text
START | UPDATE | END
```

| Situation | Result |
|---|---|
| First `NOT_WORN` observation | Enter candidate state |
| Violation survives dwell requirement | Emit `START` |
| Severity or relevant evidence changes | Emit `UPDATE` only when needed |
| Stable `WORN` evidence | Emit `END/COMPLIANCE_RESTORED` |
| Track is briefly lost | Keep active event during the grace window |
| Track is removed | Emit `END/TRACK_ENDED` |
| Run stops | Emit `END/RUN_ENDED` |

`UNKNOWN` does not open a new violation and does not by itself prove that an active violation has been resolved.

Snapshots are created for meaningful event evidence instead of every frame. This keeps the event log compact and prevents repeated alerts from intermittent detections.
