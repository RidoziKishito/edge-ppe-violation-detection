# Logging, tests and current limits

## Structured event output

The CSV writer retains the legacy fields and adds:

- `schema_version`, `run_id`, `event_id`;
- `event_action`, `event_status`;
- `track_id`, `worker_key`;
- `ppe_type`, `ppe_state`;
- association confidence and method;
- state reason code;
- start/end frames and duration.

This allows the dashboard to display the latest run while keeping worker-level events available for later analysis. A prepared evidence snapshot and scene metadata are preserved when a `START` event is written.

## Automated checks completed

| Area | Contract verified |
|---|---|
| Multiple workers | Two workers in one zone remain separate |
| Temporal lifecycle | Sustained violation creates one event instead of one alert per frame |
| Track loss | Short loss does not immediately end or duplicate an event |
| Track removal | Removed track closes its active event |
| Compliance restored | Stable `WORN` evidence closes the event |
| Unknown evidence | `UNKNOWN` neither creates a violation nor immediately closes a confirmed one |
| Four-label scope | `no_helmet` and `no_vest` create the correct `NOT_WORN` states |
| Conflicting evidence | Positive and negative evidence becomes `UNKNOWN` |
| Ownership | One PPE box is not shared by overlapping Person boxes |
| Logger compatibility | New worker-event fields coexist with legacy columns |
| Snapshot metadata | Start evidence and scene data are preserved |

## Current limits that are not hidden by the Done status

- The system does not claim long-term identity after ByteTrack removes a track.
- Missing PPE evidence is `UNKNOWN`; current code does not infer true body-part visibility.
- Association still depends on box geometry and detector quality.
- Event correctness under dense occlusion must be measured on representative videos.
- Dashboard summaries mainly consume confirmed event starts; complete lifecycle analytics can be expanded later without changing the contract.

## Handoff to remaining tasks

- **Task 21:** prepare and annotate evaluation clips.
- **Task 23:** tune tracker thresholds and report tracking metrics.
- **Task 24:** measure worker–PPE association and event precision/recall.
- **Task 25:** document failure cases and mitigation choices.

The implementation is complete enough for those evaluations to use a stable contract rather than ad-hoc frame logs.

