# Task 22 — Integrate ByteTrack for anonymous worker IDs

**Status:** Done at implementation and contract-test level.

## Purpose

Add a lightweight tracking layer after Person detection so the same visible worker can keep an anonymous `track_id` across consecutive frames. The ID is scoped to one video run; it is not a personal identity and does not use face recognition or ReID.

## Completed work

- Added a ByteTrack wrapper that accepts only Person detections and returns active tracks, lost IDs and removed IDs.
- Connected Person detection → ByteTrack → worker-centric state/event processing.
- Kept the four-label PPE detector scope: `helmet`, `no_helmet`, `vest`, `no_vest`.
- Added separate Person-model support so weak or missing Person labels in the PPE model do not block tracking.
- Added tracker reset at a new run and lifecycle handling for temporarily lost and permanently removed tracks.
- Added unit tests for ID persistence, weak-detection recovery and dual-detector routing.

## Main outputs

- [person_tracker.py](../../../edge-pipeline/person_tracker.py)
- [edge_infer.py](../../../edge-pipeline/edge_infer.py)
- [test_person_tracker.py](../../../edge-pipeline/tests/test_person_tracker.py)
- [test_dual_detector.py](../../../edge-pipeline/tests/test_dual_detector.py)

## Why this task is marked Done

The tracker is implemented, connected to the runtime pipeline and covered by contract tests. Selecting final thresholds and measuring ID stability on difficult videos are evaluation tasks, not missing integration code.

## Work continued in later tasks

- **Task 23:** tune ByteTrack parameters and report tracking metrics.
- **Task 24:** validate worker–PPE association on multi-worker video.
- **Task 25:** analyse occlusion, small-worker and ID-switch failures.

