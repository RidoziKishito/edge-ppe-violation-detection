# Run the dashboard locally

From the repository root, install the existing pipeline and dashboard requirements, then run:

```sh
python dashboard/run_local.py
```

Open `http://127.0.0.1:5055` (`TRINITY_PORT` can override the port). The launcher uses `.venv-dashboard` when available; otherwise it uses your active Python environment. Under **Live Monitor → Input source → Input video**, select a local video, or upload one from your computer (up to 2 GB). Use **Start detection** and **Stop** in Live view; no per-video CLI command is needed. Change camera is a placeholder.

The supplied YOLO26 ONNX model was exported with Ultralytics **8.4.56** and end-to-end output `[batch, 300, 6]`. Use the pinned pipeline requirements: the previously installed **8.3.240** does not interpret this export correctly and can silently return no detections. Start now rejects that old runtime rather than showing a misleading live stream. On another machine, create an environment and install the pipeline/dashboard requirements there; do not copy a Windows virtual environment between computers.

Live view and Zone editor use a full-width camera workspace with vertical scrolling. Recent alerts and the zone profile sit below the image. Other desktop tabs retain their compact viewport layout. Tab navigation uses a short fade/slide transition, with reduced-motion preferences respected and an entrance-animation fallback for older browsers.

After Start, **Starting / Loading model** remains visible until the first detection finishes. CPU initialization can take several seconds. The monitor then shows the processed frame count, source-video time and actual processing FPS; an empty detection count does not mean playback is stopped. `progress.json` and the unbuffered `pipeline.log` are saved in the active run folder. If HTTP frame pushes fail, the preview falls back to the latest JPEG written by the pipeline. Stop requests a clean shutdown to finalize the output MP4, with forced termination only after a 15-second timeout.

## Portable media layout

Place downloaded CMOT videos in this repository-relative layout:

```text
edge-pipeline/media/videos/input/
  CMOT/
    train/*.mp4
    valid/*.mp4
    test/*.mp4
  other-video.mp4
```

The library and numeric Camera/video suggestions read the actual filenames, preserving leading zeros. `val` and `validation` folders are also accepted as the valid split. Videos are ignored by Git: copy/download this directory when setting up another computer. No Windows drive letter is required. Optional `TRINITY_CMOT_DIR` overrides the CMOT root; a relative value is resolved from the repository root.

Put `baseline_yolo26n_best.onnx` in `models/` or `edge-pipeline/`, or set `TRINITY_MODEL` to an absolute or repository-relative ONNX path. The model used by the previous local run is reused when still available.

## Reviewing saved runs

Each detection run is stored separately under `edge-pipeline/logs/runs/<run_id>/`; replaying the same input creates a new folder, not an overwrite. After completion, click **View saved run & logs** in Live Monitor, or open **Event Log → Detection runs** and select a run. Use **Refresh history** to pick up runs completed in another tab.

- `output.mp4`: annotated video; download it from the selected run and open in a local video player (the existing MPEG-4 codec is not supported by every browser).
- `events.csv` and `snapshots/`: recorded safety alerts and their evidence images, viewable from event rows. Zero alerts still produces a saved run and CSV header; it does not mean all people were compliant.
- `pipeline.log`: runtime output/errors, shown in a collapsible panel (last 64 KB) and downloadable in full.
- `run.json`, `progress.json`: model/runtime settings, status, frame counts and processing progress.
- `zones_snapshot.json`: zone configuration at the start of new runs; older runs may not have this file. Live zone edits are not a frame-by-frame zone revision history.

Active runs do not offer unfinished video downloads. Stop preserves a partial video when graceful shutdown succeeds; failed/force-terminated runs may have an incomplete MP4. Viewing an archive does not switch or restart the currently active detector. Files remain local and are not uploaded or deleted automatically.

## Polygon assets

1. Select a video; the first frame appears without starting inference.
2. Open the **Zone editor** subtab; add/select a warning or danger polygon and edit vertices.
3. Enter an asset name and click **Save asset**.
4. In **Live view**, choose **Zone assets** and apply it. The raw source preview displays the saved polygons immediately. Start detection to use those rules in inference.

Assets are stored in `dashboard/data/zone_assets/` and only offered for their original video. Names identify versions: the same name updates an asset; a new name creates another asset. Copy the asset folder along with the unchanged media layout to another computer. Working profiles live in `edge-pipeline/configs/zones/input_*.json`. Saving creates a backup of the working profile.

Event Log includes history across local runs. Camera/video accepts numeric prefixes and supports arrow keys/Enter. The Zone selector has Warning and Danger categories, plus an unfiltered All zones state. This is a local, single-operator demo server; it is not intended for public deployment.
