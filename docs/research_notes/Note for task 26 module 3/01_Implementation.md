# Worker state and event lifecycle implementation

## Current data flow

```text
Person track_id
  + associated helmet/vest evidence
  + zone membership
  → WorkerState
  → temporal confirmation
  → WorkerEvent START / UPDATE / END
  → CSV, snapshot, output video and dashboard
```

## WorkerState contract

Each active worker state contains:

- schema version, `run_id`, camera ID and frame timestamp;
- anonymous `track_id` and track status;
- Person box, confidence and foot point;
- active warning/danger zones;
- helmet and vest state, confidence, association method and reason code.

The worker key is scoped by camera, run and track. It prevents two workers in the same polygon from sharing one alert state.

## PPE state rules

| Detector evidence | Runtime state | Reason |
|---|---|---|
| `helmet` or `vest` | `WORN` | Positive evidence exists |
| `no_helmet` or `no_vest` | `NOT_WORN` | Negative evidence exists |
| Positive and negative together | `UNKNOWN` | Conflicting evidence |
| No usable evidence | `UNKNOWN` | No PPE evidence |

`UNKNOWN` means the current frame is not strong enough to change the conclusion. It is not automatically converted into a violation.

## Association used by the current system

The PPE-box centre must fall inside exactly one active Person box:

- one valid owner → associate the evidence with that worker;
- no owner → leave it unassigned;
- more than one valid owner → mark it ambiguous and do not share it between workers.

This preserves the existing lightweight geometry while preventing one PPE detection from being counted for two overlapping Person boxes.

## Event lifecycle

- `START`: a `NOT_WORN` observation remains valid for the configured confirmation period.
- `UPDATE`: an active event changes severity or receives a meaningful state update.
- `END`: compliance is restored, the track is removed, or the run ends.
- A temporarily lost track does not immediately end the event.
- `UNKNOWN` does not open a new violation and does not immediately close an active confirmed event.

Event ownership is separated by worker and PPE type. A worker missing both helmet and vest therefore has two independently traceable event lifecycles.

