"""
Run 1 -- Baseline YOLO26n Training on Modal A100
================================================
Construction Site PPE Safety Detection

This script trains a baseline YOLO26n model on the Construction-PPE dataset
using Modal's A100-40GB GPU infrastructure. It serves as the reference
benchmark for all subsequent architecture improvements.

Key configurations:
- Model: yolo26n.pt (pretrained on COCO)
- Optimizer: AdamW with cosine LR schedule
- Batch: Auto (YOLO selects optimal batch for A100-40GB VRAM)
- Class imbalance: Addressed via label_smoothing + augmentation
- Seed: 42 for reproducibility

Usage:
    modal run train_baseline.py
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

# Persistent volume for saving weights, logs, and exports across runs
volume = modal.Volume.from_name("ppe-training-vol", create_if_missing=True)

# Dataset volume (uploaded once via upload_dataset.py, reused across runs)
dataset_volume = modal.Volume.from_name("ppe-dataset-vol", create_if_missing=True)

# Container image with all required dependencies
# Using latest ultralytics (>=8.4) which includes YOLO26 support
# Dataset is mounted from a Modal Volume (not baked into image) for speed
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
    # Mount Modal-compatible data YAML into container
    .add_local_file(str(_CONFIGS_DIR / "data_modal.yaml"), remote_path="/config/data_modal.yaml")
)


@app.function(
    image=image,
    gpu="L4",                                # L4-24GB
    timeout=21600,                           # 6 hours max
    volumes={
        "/runs": volume,                     # Training outputs
        "/dataset": dataset_volume,          # Dataset (read-only)
    },
)
def train_baseline():
    """
    Run 1 -- Baseline YOLO26n Training

    Strategy for class imbalance (no_helmet, no_goggle, no_gloves, no_boots):
    - label_smoothing=0.1: Prevents overconfident predictions on majority classes
    - mosaic=1.0: Aggressive mosaic augmentation to mix rare class images
    - mixup=0.15: MixUp probability to increase diversity of rare class samples
    - copy_paste=0.1: Copy-paste augmentation for underrepresented objects
    - batch=-1: Auto-selects optimal batch size for A100-40GB VRAM

    These settings partially mitigate the severe imbalance in no_* classes
    (e.g., no_boots has only ~2 val images). Full mitigation requires
    oversampling or class merging, documented in the guide.
    """
    from ultralytics import YOLO
    import yaml

    # Verify dataset mount
    import os
    print("=" * 60)
    print("DATASET VERIFICATION")
    print("=" * 60)
    for split in ["train", "val", "test"]:
        img_path = f"/dataset/images/{split}"
        lbl_path = f"/dataset/labels/{split}"
        if os.path.exists(img_path):
            n_imgs = len(os.listdir(img_path))
            n_lbls = len(os.listdir(lbl_path)) if os.path.exists(lbl_path) else 0
            print(f"  {split}: {n_imgs} images, {n_lbls} labels")
        else:
            print(f"  {split}: NOT FOUND at {img_path}")

    # Verify data_modal.yaml exists
    yaml_path = "/config/data_modal.yaml"
    if not os.path.exists(yaml_path):
        # Fallback: use the data.yaml but override the path
        yaml_path = "/dataset/data.yaml"
        print(f"\nUsing fallback: {yaml_path}")

    print(f"\nDataset config: {yaml_path}")
    with open(yaml_path) as f:
        print(yaml.safe_load(f))
    print("=" * 60)

    # Load pretrained YOLO26n
    model = YOLO("yolo26n.pt")
    print(f"\nModel loaded: {model.model_name}")
    print(f"Parameters: {sum(p.numel() for p in model.model.parameters()):,}")

    # Train baseline
    results = model.train(
        data=yaml_path,
        epochs=50,                  # 50 epochs for 30k images (sufficient convergence)
        imgsz=640,
        batch=64,                   # Auto batch: YOLO finds optimal for A100-40GB
        device=0,
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,                   # Final LR = lr0 * lrf
        warmup_epochs=5,
        cos_lr=True,
        label_smoothing=0.1,
        # Augmentation settings (class imbalance mitigation)
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.1,
        degrees=10.0,
        translate=0.2,
        scale=0.5,
        fliplr=0.5,
        # Training settings
        pretrained=True,
        project="/runs/detect",
        name="baseline_yolo26n",
        seed=42,
        # Logging
        plots=True,
        save=True,
        save_period=10,             # Checkpoint every 10 epochs
    )

    # Validate on test set
    print("\n" + "=" * 60)
    print("TEST SET EVALUATION")
    print("=" * 60)
    metrics = model.val(
        data=yaml_path,
        split="test",
        project="/runs/detect",
        name="baseline_yolo26n_test",
    )
    print(f"mAP@0.5     : {metrics.box.map50:.4f}")
    print(f"mAP@0.5:0.95: {metrics.box.map:.4f}")
    print(f"Precision    : {metrics.box.mp:.4f}")
    print(f"Recall       : {metrics.box.mr:.4f}")

    # Print per-class metrics (critical for no_* violation classes)
    print("\nPer-class mAP@0.5:")
    class_names = metrics.names
    for i, (name, ap50) in enumerate(zip(class_names.values(), metrics.box.ap50)):
        flag = " [!]" if name.startswith("no_") else ""
        print(f"  [{i:2d}] {name:12s}: {ap50:.4f}{flag}")

    # Commit all results to persistent volume
    volume.commit()

    return str(results.save_dir)


@app.local_entrypoint()
def main():
    """Launch baseline training on Modal."""
    print("Starting Run 1 -- Baseline YOLO26n Training")
    print("   Monitor at: https://modal.com/apps")
    save_dir = train_baseline.remote()
    print(f"\nTraining complete!")
    print(f"   Results saved to volume: {save_dir}")
    print(f"\nDownload results with:")
    print(f"   modal volume get ppe-training-vol /runs ./local_runs")
