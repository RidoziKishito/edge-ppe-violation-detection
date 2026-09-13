"""
Run 3 -- YOLO26n + Ghost Convolution (Lightweight) Training on Modal A100
========================================================================
Construction Site PPE Safety Detection

This script trains a lightweight YOLO26n model where standard Conv layers
in the backbone are replaced with GhostConv modules. GhostConv generates
feature maps using "cheap" linear operations instead of full convolutions,
reducing parameters by ~20-30% with minimal accuracy drop.

Reference:
    Han et al., "GhostNet: More Features from Cheap Operations", CVPR 2020

Architecture changes:
    - Backbone Conv -> GhostConv (layers 0, 1, 3, 5, 7)
    - Head downsampling Conv -> GhostConv (layers 17, 20)
    - C3k2 blocks unchanged to preserve feature quality
    - Target: ~20-30% fewer parameters, <1% mAP drop vs baseline

Usage:
    modal run train_ghost.py
"""

import modal
from pathlib import Path

# ---------------------------------------------------------------------------
# Modal App & Infrastructure
# ---------------------------------------------------------------------------
# Resolve config paths relative to this script, not CWD
_SCRIPT_DIR = Path(__file__).resolve().parent
_CONFIGS_DIR = _SCRIPT_DIR.parent / "configs"

app = modal.App("ppe-yolo26-training")

volume = modal.Volume.from_name("ppe-training-vol", create_if_missing=True)
dataset_volume = modal.Volume.from_name("ppe-dataset-vol", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0", "libglib2.0-dev")
    .pip_install(
        "ultralytics>=8.4.0",
        "torch",
        "torchvision",
        "onnx",
        "onnxruntime",
    )
    # Config files only -- dataset comes from volume
    .add_local_file(str(_CONFIGS_DIR / "yolo26n-ghost.yaml"), remote_path="/config/yolo26n-ghost.yaml")
    .add_local_file(str(_CONFIGS_DIR / "data_modal.yaml"), remote_path="/config/data_modal.yaml")
)


@app.function(
    image=image,
    gpu="L4",                                # L4-24GB
    timeout=21600,                           # 6 hours max
    volumes={
        "/runs": volume,
        "/dataset": dataset_volume,
    },
)
def train_ghost():
    """
    Run 3 -- YOLO26n + Ghost Convolution Training

    GhostConv is a built-in module in ultralytics (nn.modules.conv.GhostConv).
    It generates feature maps through two steps:
    1. Standard convolution on a subset of channels (intrinsic features)
    2. Cheap linear operations to generate remaining "ghost" features

    This reduces computational cost while maintaining representational capacity.
    The model is trained from scratch since the architecture differs from baseline.
    """
    from ultralytics import YOLO
    import os

    yaml_path = "/config/data_modal.yaml"
    if not os.path.exists(yaml_path):
        yaml_path = "/dataset/data.yaml"

    model_yaml = "/config/yolo26n-ghost.yaml"
    print(f"Model config: {model_yaml}")
    print(f"Dataset config: {yaml_path}")

    # Build model from Ghost Conv YAML
    model = YOLO(model_yaml)
    total_params = sum(p.numel() for p in model.model.parameters())
    print(f"\nModel architecture: YOLO26n + GhostConv")
    print(f"Total parameters: {total_params:,}")

    # Compare with baseline parameter count for reference
    baseline_params = 2_572_280  # yolo26n baseline (from yolo26.yaml)
    reduction = (1 - total_params / baseline_params) * 100
    print(f"Baseline params: {baseline_params:,}")
    print(f"Parameter reduction: {reduction:.1f}%")

    # Train
    results = model.train(
        data=yaml_path,
        epochs=50,                  # 50 epochs for 30k images
        imgsz=640,
        batch=64,                   # Auto batch for A100-40GB
        device=0,
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,
        warmup_epochs=5,
        cos_lr=True,
        label_smoothing=0.1,
        # Same augmentation as baseline for fair comparison
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.1,
        degrees=10.0,
        translate=0.2,
        scale=0.5,
        fliplr=0.5,
        # Training settings
        pretrained=False,
        project="/runs/detect",
        name="ghost_conv",
        seed=42,
        plots=True,
        save=True,
        save_period=10,
    )

    # Validate on test set
    print("\n" + "=" * 60)
    print("TEST SET EVALUATION -- YOLO26n + GhostConv")
    print("=" * 60)
    metrics = model.val(
        data=yaml_path,
        split="test",
        project="/runs/detect",
        name="ghost_conv_test",
    )
    print(f"mAP@0.5     : {metrics.box.map50:.4f}")
    print(f"mAP@0.5:0.95: {metrics.box.map:.4f}")
    print(f"Precision    : {metrics.box.mp:.4f}")
    print(f"Recall       : {metrics.box.mr:.4f}")

    # Per-class metrics
    print("\nPer-class mAP@0.5:")
    class_names = metrics.names
    for i, (name, ap50) in enumerate(zip(class_names.values(), metrics.box.ap50)):
        flag = " [!]" if name.startswith("no_") else ""
        print(f"  [{i:2d}] {name:12s}: {ap50:.4f}{flag}")

    # Report efficiency metrics
    print(f"\nEfficiency Summary:")
    print(f"   Total parameters: {total_params:,}")
    print(f"   Param reduction:  {reduction:.1f}%")

    volume.commit()
    return str(results.save_dir)


@app.local_entrypoint()
def main():
    """Launch Ghost Conv training on Modal."""
    print("Starting Run 3 -- YOLO26n + Ghost Convolution Training")
    print("   Monitor at: https://modal.com/apps")
    save_dir = train_ghost.remote()
    print(f"\nTraining complete!")
    print(f"   Results saved to volume: {save_dir}")
    print(f"\nDownload results with:")
    print(f"   modal volume get ppe-training-vol /runs ./local_runs")
