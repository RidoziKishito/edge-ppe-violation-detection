# 04 - Model and small-object study

## Current experiments

| Experiment | Purpose | Current decision |
|---|---|---|
| Original YOLO26n | Four-label baseline | Reference |
| DetectionHead | Adds the P2 detection head | Current detector candidate |
| E2 Domain Generalization | Tests source-balanced training | Research result, not deployment candidate |
| A1 Sampling | Samples more images containing small objects | Completed; compare AP_small and overall AP |
| A2 Object-Centered Crop | Adds crops around small PPE | Pending evaluation |
| A3 Controlled Multi-Scale | Combines the staged small-object recipe | Training must finish before final comparison |

DetectionHead improves the comparable full-validation result while keeping the model small. The final model must be selected from controlled experiments using the same validation protocol.

## Metrics

- Precision, recall, mAP@50 and mAP@50-95.
- Per-class AP for the four labels.
- AP_small, AP_medium and AP_large when available.
- Parameters, weight size and batch-1 latency.

## Scope boundary

The active study focuses on detector architecture and training data sampling. SAHI, person-crop inference, low-light enhancement, deblur, super-resolution and BiFPN are not part of the current release unless a separate controlled result later justifies them.

See [YOLO26n_Model_Comparison_Summary.md](../YOLO26n_Model_Comparison_Summary.md) for the compact model comparison.

