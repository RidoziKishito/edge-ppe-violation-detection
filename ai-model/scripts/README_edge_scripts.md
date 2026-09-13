# Local Edge Optimization Scripts

These scripts convert the edge optimization notebook workflows into local,
CPU-friendly Python entry points. Run all commands from the repository root.

## Dependencies

Required packages:

```bash
pip install onnxruntime opencv-python numpy ultralytics pandas
```

Optional package for FP16 ONNX conversion:

```bash
pip install onnxconverter-common onnx
```

The INT8 path uses `onnxruntime.quantization`, which is included with common
ONNXRuntime installs. If FP16 or INT8 conversion is unavailable, the latency
script keeps the FP32 baseline and prints a clear warning.

## Model Discovery

The scripts auto-detect the selected deployment model in this order:

1. `ai-model/outputs/baseline_yolo26n/ppe_experiment_package/exports/baseline_yolo26n_best.onnx`
2. `ai-model/outputs/baseline_yolo26n/weights/best.onnx`
3. `ai-model/best.onnx`

## Scripts

### Latency and Quantization

```bash
python ai-model/scripts/edge_latency_benchmark.py
```

Outputs:

- `ai-model/outputs/edge_results/latency_quantization_summary.csv`
- `ai-model/outputs/edge_results/onnx_variants/baseline_yolo26n_fp32.onnx`
- Optional FP16 and INT8 variants in the same `onnx_variants/` directory

CSV columns:

```text
variant,batch_size,model_size_mb,latency_ms_per_img,fps,notes
```

### Temporal Smoothing

```bash
python ai-model/scripts/edge_temporal_smoothing.py
```

This script runs the selected ONNX model on:

- `edge-pipeline/demo_video3.mp4`
- `edge-pipeline/demo_video4.mp4`

It reuses `edge-pipeline/rule_engine.py` and
`edge-pipeline/configs/zones.json`. Results are pseudo-stability metrics only;
no ground-truth annotations are used.

Output:

- `ai-model/outputs/edge_results/event_vs_frame_metrics.csv`

CSV columns:

```text
video,level,N_frames,total_frames,warning_count,critical_count,alert_rate,fp_reduction_pct
```

### Bandwidth Analysis

```bash
python ai-model/scripts/edge_bandwidth_analysis.py
```

This script measures the demo video file sizes and durations, then compares:

- Scenario A - continuous demo-video streaming
- Scenario A reference - continuous 1080p 2 Mbps streaming
- Scenario B - edge logs + violation snapshots
- Scenario C - logs + blurred critical frames

Output:

- `ai-model/outputs/edge_results/bandwidth_summary.csv`

CSV columns:

```text
scenario,time_period,data_mb,bandwidth_reduction_pct,notes
```

## Expected Output Directory

All results are written under:

```text
ai-model/outputs/edge_results/
```

Each script prints environment information, a summary table, and a final
`DONE - results saved to ...` message.
