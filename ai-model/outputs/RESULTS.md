# Trinity Edge AI — Experiment Results

This file summarises all AI and edge optimisation experiments conducted for the Trinity construction-site safety system. Raw CSV outputs are stored alongside this file in `ai-model/outputs/` and `ai-model/outputs/edge_results/`.

---

## 1. Model Ablation Study

**Objective:** Identify the best YOLO26n variant for edge deployment across accuracy, violation detection, and inference speed.

**Training environment:** Modal Labs · NVIDIA L4 (22 563 MiB) · Ultralytics 8.4.45 · PyTorch 2.11.0+cu130

### Val-set summary (all 2 663 images)

| Rank | Experiment | mAP@0.5 | Violation mAP@0.5 | Infer (ms/img) | Deploy recommendation |
|------|------------|---------|-------------------|----------------|-----------------------|
| 1 | **baseline_yolo26n** | 0.677 | 0.580 | **2.93** |  Edge deploy — fastest top-tier violation model |
| 2 | baseline_violation_oversample | **0.690** | **0.586** | 3.18 | Paper/report — best absolute mAP, slightly slower |
| 3 | baseline_violation_aug | 0.670 | 0.557 | 2.95 | Not recommended — augmentation underperforms |
| 4 | ghost_violation_oversample | 0.629 | 0.556 | 3.21 | Ablation only |
| 5 | cbam_violation_oversample | 0.642 | 0.553 | 3.15 | Ablation only |
| 6 | cbam_existing_repro | 0.618 | 0.525 | 3.15 | Not recommended |
| 7 | ghost_existing_repro | 0.613 | 0.518 | 3.11 | Not recommended |

> Source: `ai-model/outputs/final_ranked_table.csv`

### Key per-class mAP@0.5 — baseline_yolo26n (val set)

| Class | mAP@0.5 |
|-------|---------|
| helmet | 0.871 |
| goggles | 0.916 |
| gloves | 0.867 |
| vest | 0.671 |
| boots | 0.682 |
| **no_helmet** | **0.800** |
| **no_goggle** | **0.817** |
| **no_gloves** | **0.744** |
| **no_boots** | 0.002 \* |
| Person | 0.694 |

\* `no_boots` is severely under-represented in the dataset (2 val images, 4 instances). This class requires additional data collection.

### Architecture comparison (GhostConv ablation)

| Variant | Params | GFLOPs | Val mAP@0.5 | Param reduction |
|---------|--------|--------|-------------|-----------------|
| Baseline | ~2.35 M | ~5.0 | **0.677** | — |
| CBAM | ~2.31 M | ~5.2 | 0.642 | −1.7% |
| GhostConv | **2.05 M** | **4.4** | 0.629 | **−12.7%** |

GhostConv reduces model size by 12.7% and GFLOPs by 12% but does not improve accuracy — baseline remains the deployment choice.

---

## 2. ONNX Export and Quantisation Benchmark

**Objective:** Measure inference latency and accuracy retention across FP32 / FP16 / INT8 ONNX variants.

**Benchmark environment:** Kaggle · NVIDIA GPU · ONNX Runtime 1.26.0 · CUDAExecutionProvider

### Latency and accuracy (val set, batch sizes 1 / 4 / 8)

| Variant | Best batch | Latency (ms/img) | FPS | Model size | mAP@0.5 | Violation mAP@0.5 |
|---------|-----------|-----------------|-----|------------|---------|-------------------|
| FP32 fixed B=1 | 1 | 8.99 | 111 | 9.4 MB | 0.747 | 0.660 |
| **FP32 dynamic** | **8** | **7.61** | **131** | 10.3 MB | 0.749 | **0.671** |
| FP16 dynamic | 4 | 9.05 | 110 | **5.7 MB** | 0.750 | 0.671 |
| INT8 dynamic | 1 | 268.7 | 3.7 | 3.7 MB | 0.757 | 0.711 |

> Source: `ai-model/outputs/edge_results/latency_quantization_summary.json`

### Key findings

- **FP32 dynamic B=8 is the deployment choice** — 131 FPS provides a 4× headroom over a 30 FPS camera stream, sufficient to run 4 cameras in parallel on a single edge GPU.
- **FP16** saves 44% model size (5.7 MB vs 10.3 MB) with identical accuracy — recommended for RAM-constrained edge devices (Jetson Nano / Orin NX 8 GB).
- **INT8 dynamic quantisation via ONNX Runtime is counter-productive on CUDA** — 30× slower than FP32. INT8 speedup requires TensorRT engine compilation, which is outside the scope of this phase.

> **Evaluation Protocol Note (mAP 0.677 vs 0.749):** The 7-model ablation in Section 1 reported baseline mAP@0.5 = **0.677** evaluated against the extended 2,663-image stratified validation split (`split_val.py`) across all 11 classes. The ONNX benchmark above reports baseline FP32 mAP@0.5 = **0.749** evaluated on the original 143-image validation split (`data_modal.yaml`) specifically to measure relative precision loss across FP32, FP16, and INT8 formats against the PyTorch reference (0.7488). Both protocols validate consistent behavior within their respective evaluation scopes.

---

## 3. Temporal Smoothing for Alert Stability

**Objective:** Reduce transient frame-level false alarms by requiring the same zone violation to persist for N consecutive frames before raising an event.

**Environment:** Kaggle · NVIDIA GPU · Ultralytics YOLO + rule_engine zone integration

**Videos tested:** `demo_video3.mp4` (153 frames), `demo_video4.mp4` (144 frames)

### Frame-level vs Event-level alerts

| Video | Total frames | Frame-level alerts | N=3 events | N=3 reduction | N=5 events | N=5 reduction | N=10 events | N=10 reduction |
|-------|--------------|--------------------|------------|---------------|------------|---------------|-------------|----------------|
| demo_video3 | 153 | 17 W / 0 C | 2 W | 88.2% | 1 W | **94.1%** | 1 W | 94.1% |
| demo_video4 | 144 | 96 W / 28 C | 8 total | 93.5% | 6 total | **95.2%** | 5 total | **96.0%** |

> Source: `ai-model/outputs/edge_results/event_vs_frame_metrics.csv`

### Recommended setting: N = 5

| N_frames | Avg FP reduction | Alert latency @ 30 FPS |
|----------|-----------------|------------------------|
| 3 | 90.9% | ~100 ms |
| **5** | **94.6%** | **~167 ms** |
| 10 | 95.0% | ~333 ms |

N=5 delivers 94.6% false-alarm reduction at only 167 ms added latency — well within the system's <200 ms alert target. The marginal gain from N=10 (+0.4%) does not justify doubling the delay.

---

## 4. Bandwidth Optimisation Analysis

**Objective:** Quantify the bandwidth savings of edge-processed event transmission versus raw video streaming.

### 1-hour data transmission comparison

| Scenario | Data / hour | vs. Raw video |
|----------|-------------|---------------|
| A — Raw demo video stream | 1 943 MB | baseline |
| A ref — 1080p @ 2 Mbps stream | 858 MB | −55.8% |
| **B — Edge logs + violation snapshots** | **1.35 MB** | **−99.93%** |
| **C — Logs + blurred critical frames** | **0.39 MB** | **−99.98%** |

> Source: `ai-model/outputs/edge_results/bandwidth_summary.csv`

Scenario B (1 event/min, 500 B log + 15–30 KB snapshot) reduces upstream bandwidth by **99.93%**, making deployment viable over standard 4G/LTE construction-site connections (typical uplink 5–10 Mbps).

---

## 5. Deployment Recommendation Summary

| Dimension | Recommended choice | Key metric |
|-----------|--------------------|------------|
| Model variant | `baseline_yolo26n` | val mAP@0.5 = 0.677, 2.93 ms/img |
| Export format (GPU edge) | FP32 dynamic ONNX, B=8 | 131 FPS |
| Export format (RAM-limited) | FP16 dynamic ONNX | 5.7 MB, same accuracy |
| Alert smoothing | N = 5 consecutive frames | 94.6% FP reduction, 167 ms latency |
| Bandwidth mode | Scenario B (logs + snapshots) | 1.35 MB/hour, −99.93% |

---

*Last updated: June 2026 — Trinity Edge AI Team, HCMUTE*
