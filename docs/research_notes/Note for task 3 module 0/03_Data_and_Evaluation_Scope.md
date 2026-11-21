# 03 - Data and evaluation scope

## Data currently used

| Resource | Role |
|---|---|
| Dataset v2 | Train and validate the four-label PPE detector |
| Dataset v1 | Legacy reference only |
| Project videos | Functional demo for helmet, vest, zones and events |
| CMOT videos | Tracking stress test and qualitative demo only |

Dataset v2 keeps source folders and four normalized labels. Detector experiments must use the same validation split for a fair comparison.

## Data no longer required

- No PPE-MOT-mini is required for the current release.
- No keypoint, pose or body-region annotation is required.
- No worker-machine, metric-distance or TTC dataset is required.
- CMOT is not merged into Dataset v2 because it does not provide the same four-label PPE task.

## Lightweight video evaluation

Select a small, fixed suite containing:

- workers entering and leaving the frame;
- short person overlap or occlusion;
- small or distant workers;
- intermittent helmet or vest detections;
- warning and danger polygons.

For each clip, record the expected qualitative behavior: stable ID where possible, no duplicated owner, event start/end, saved output video and readable log. This suite validates integration without creating a new training dataset.

