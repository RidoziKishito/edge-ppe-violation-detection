# YOLO26n Model Comparison

## 1. Model settings

All three experiments detect the same four PPE labels: `helmet`, `no-helmet`, `vest`, and `no-vest`.

| Experiment | Architecture | Main training setting |
|---|---|---|
| Original | Standard YOLO26n with P3, P4, and P5 heads | Four-label baseline |
| DetectionHead | YOLO26n with an additional P2 detection head | Preserves higher-resolution features for small PPE |
| Domain Generalization | Same DetectionHead architecture | Source-balanced training and controlled augmentation |

## 2. Overall results

| Metric | Original | DetectionHead | Domain Generalization* |
|---|---:|---:|---:|
| Precision | 74.63% | **75.07%** | 74.20% |
| Recall | 74.94% | 76.00% | **79.60%** |
| mAP@50 | 78.62% | **80.15%** | 80.00% |
| mAP@50–95 | 47.98% | 48.85% | **52.80%** |

\* Original and DetectionHead use the same full validation set. Domain Generalization uses its internal seen-source validation set, so its values are shown for reference but are not a fully fair direct comparison.

## 3. AP@50–95 by class

| Class | Original | DetectionHead | Domain Generalization* |
|---|---:|---:|---:|
| Helmet | 43.33% | 43.73% | **46.50%** |
| No helmet | 37.57% | 40.63% | **44.10%** |
| Vest | 58.83% | 58.53% | **63.30%** |
| No vest | 52.20% | 52.51% | **57.20%** |

## 4. Model size and small-object result

| Property | Original | DetectionHead | Domain Generalization |
|---|---:|---:|---:|
| Parameters | About 2.39 M | About 2.61 M | About 2.61 M |
| Weight size | About 5.5 MB | About 5.59 MB | About 5.9 MB |
| Small-object AP@50–95 | Not separately reported | 24.91% | Not separately reported |

## 5. Conclusion

- **Original** remains the lightweight scientific baseline.
- **DetectionHead** is the best directly verified improvement because it outperforms Original on the same validation set while increasing model size only slightly.
- **Domain Generalization** has the highest internal mAP@50–95, but it achieved only 19.40% mAP@50–95 on the held-out CSS source. It is therefore an additional research experiment, not the current deployment model.
- **DetectionHead** remains the model selected for edge deployment and later TensorRT benchmarking.

## Related notebooks

- [Original](../../notebooks/PPE_Baseline_YOLO26n.ipynb)
- [DetectionHead](../../notebooks/PPE_YOLO26n_DetectionHead.ipynb)
- [Domain Generalization](../../notebooks/PPE_YOLO26n_DetectionHead_E2_Domain_Generalization.ipynb)
