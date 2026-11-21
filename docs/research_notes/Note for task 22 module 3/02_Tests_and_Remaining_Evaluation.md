# Tests and remaining evaluation

## Automated checks completed

| Test area | Evidence |
|---|---|
| Default retention window | Confirms the tracker uses 60 updates by default |
| Weak-detection recovery | Confirms a lower-confidence Person detection can keep an existing track |
| ID and lifecycle contract | Confirms active, lost and removed states are reported |
| Dual-detector routing | Confirms the Person model requests only Person detections |
| PPE detector isolation | Confirms a weak Person class from the PPE model is not reused when a separate Person detector is active |

Tests are in [test_person_tracker.py](../../../edge-pipeline/tests/test_person_tracker.py) and [test_dual_detector.py](../../../edge-pipeline/tests/test_dual_detector.py).

## Confirmed limitations

- ByteTrack does not remember a person's identity after a long disappearance.
- It can still switch IDs during severe occlusion, missed Person detection or abrupt motion.
- `track_buffer=60` means tracker updates, not necessarily 60 original video frames when frame skipping is enabled.
- Unit tests verify software behaviour but do not replace a video benchmark.

## Required evaluation after Task 22

1. Run representative videos with multiple overlapping workers.
2. Record ID switches, track fragmentation and recovered tracks.
3. Compare a small threshold grid in Task 23 rather than tuning from one video.
4. Inspect whether a changed ID incorrectly starts a duplicate PPE event in Tasks 24–25.

Therefore, **Task 22 is complete as integration**, while its empirical tuning and failure analysis remain explicitly separated.

