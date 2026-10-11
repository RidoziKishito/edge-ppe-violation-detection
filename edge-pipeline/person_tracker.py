"""Lightweight adapter around Ultralytics ByteTrack for Person detections only."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np


@dataclass
class TrackingResult:
    active: list[dict]
    lost_track_ids: set[int]
    removed_track_ids: set[int]


class PersonTracker:
    """Keep temporary worker IDs without tracking PPE boxes or using ReID."""

    def __init__(
        self,
        track_high_thresh=0.25,
        track_low_thresh=0.1,
        new_track_thresh=0.25,
        track_buffer=30,
        match_thresh=0.8,
    ):
        try:
            from ultralytics.engine.results import Boxes
            from ultralytics.trackers.byte_tracker import BYTETracker
        except ModuleNotFoundError as exc:
            if exc.name == "lap":
                raise RuntimeError(
                    "ByteTrack requires the 'lap' package. Install edge-pipeline/requirements.txt."
                ) from exc
            raise

        args = SimpleNamespace(
            track_high_thresh=float(track_high_thresh),
            track_low_thresh=float(track_low_thresh),
            new_track_thresh=float(new_track_thresh),
            track_buffer=max(1, int(track_buffer)),
            match_thresh=float(match_thresh),
            fuse_score=True,
        )
        self._boxes_type = Boxes
        self._tracker = BYTETracker(args=args)
        self._reported_removed_ids: set[int] = set()

    def update(self, persons, frame) -> TrackingResult:
        """Update ByteTrack once per inference frame and return confirmed tracks."""
        rows = []
        for person in persons:
            x1, y1, x2, y2 = person["box"]
            rows.append(
                [
                    float(x1),
                    float(y1),
                    float(x2),
                    float(y2),
                    float(person["conf"]),
                    0.0,
                ]
            )
        data = np.asarray(rows, dtype=np.float32)
        if not len(rows):
            data = np.empty((0, 6), dtype=np.float32)

        boxes = self._boxes_type(data, frame.shape[:2])
        tracks = self._tracker.update(boxes, frame)
        active = []
        for track in tracks:
            x1, y1, x2, y2, track_id, score, _class_id, _source_index = track
            active.append(
                {
                    "box": tuple(map(int, (x1, y1, x2, y2))),
                    "conf": round(float(score), 4),
                    "class_name": "Person",
                    "track_id": int(track_id),
                    "track_status": "CONFIRMED",
                }
            )

        lost_ids = {int(track.track_id) for track in self._tracker.lost_stracks}
        all_removed_ids = {
            int(track.track_id) for track in self._tracker.removed_stracks
        }
        removed_ids = all_removed_ids - self._reported_removed_ids
        self._reported_removed_ids.update(removed_ids)
        return TrackingResult(active, lost_ids, removed_ids)

    def reset(self):
        self._tracker.reset()
        self._reported_removed_ids.clear()
