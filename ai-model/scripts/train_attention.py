"""
Run 2 -- YOLO26n + CBAM Attention Module Training on Modal A100
==============================================================
Construction Site PPE Safety Detection

This script trains a YOLO26n model enhanced with CBAM (Convolutional Block
Attention Module) on the Construction-PPE dataset. CBAM applies channel-wise
and spatial attention sequentially to improve feature representation,
particularly effective for detecting small PPE objects (gloves, goggles)
in complex construction site backgrounds.

Reference:
    Woo et al., "CBAM: Convolutional Block Attention Module", ECCV 2018

Architecture changes:
    - CBAM blocks inserted after each C3k2 in the YOLO26 head/neck
    - Channel attention: Global avg + max pool -> shared MLP -> sigmoid
    - Spatial attention: Channel-wise avg + max -> 7x7 conv -> sigmoid

Usage:
    modal run train_attention.py
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
    # Mount config files into the container (dataset comes from volume)
    .add_local_file(str(_CONFIGS_DIR / "data_modal.yaml"), remote_path="/config/data_modal.yaml")
    .add_local_file(str(_CONFIGS_DIR / "yolo26n-cbam.yaml"), remote_path="/config/yolo26n-cbam.yaml")
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
def train_attention():
    """
    Run 2 -- YOLO26n + CBAM Attention Training

    CBAM integration approach:
    Since CBAM is already registered in the ultralytics module system
    (ultralytics.nn.modules.conv.CBAM), we can reference it directly
    in the custom YAML config. The model is built from the YAML definition,
    not from pretrained weights -- this ensures the attention blocks
    are properly initialized.

    Training starts from scratch (no transfer from baseline) because
    the architecture has changed. YOLO26n backbone weights are still
    loaded from yolo26n.pt where layer shapes match.
    """
    from ultralytics import YOLO
    import os

    # Verify files
    yaml_path = "/config/data_modal.yaml"
    if not os.path.exists(yaml_path):
        yaml_path = "/dataset/data.yaml"

    model_yaml = "/config/yolo26n-cbam.yaml"
    print(f"Model config: {model_yaml}")
    print(f"Dataset config: {yaml_path}")

    # Verify CBAM is available in ultralytics
    try:
        from ultralytics.nn.modules.conv import CBAM
        print(f"[OK] CBAM module found: {CBAM}")
    except ImportError:
        print("[WARN] CBAM not found in ultralytics.nn.modules.conv")
        print("   Attempting to check ultralytics.nn.modules.block...")
        try:
            from ultralytics.nn.modules.block import CBAM
            print(f"[OK] CBAM module found in block: {CBAM}")
        except ImportError:
            print("[ERROR] CBAM not available -- falling back to baseline architecture")
            model_yaml = "yolo26n.pt"

    # Build model from custom YAML (CBAM architecture)
    # This creates a new model with CBAM blocks; backbone weights
    # from yolo26n.pt will be transferred where shapes match
    from ultralytics.nn.modules.conv import CBAM # FIX
    import ultralytics.nn.tasks as nn_tasks # FIX
    nn_tasks.CBAM = CBAM # FIX
    assert hasattr(nn_tasks, 'CBAM'), "CBAM not registered in tasks namespace" # FIX
    model = YOLO(model_yaml)
    print(f"\nModel architecture built from: {model_yaml}")
    total_params = sum(p.numel() for p in model.model.parameters())
    print(f"Total parameters: {total_params:,}")

    # Train with CBAM
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
        # Augmentation (same as baseline for fair comparison)
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.1,
        degrees=10.0,
        translate=0.2,
        scale=0.5,
        fliplr=0.5,
        # Training settings
        pretrained=True,  # Building from YAML, not pretrained weights
        project="/runs/detect",
        name="attention_cbam",
        seed=42,
        plots=True,
        save=True,
        save_period=10,
    )

    # Validate on test set
    print("\n" + "=" * 60)
    print("TEST SET EVALUATION -- YOLO26n + CBAM")
    print("=" * 60)
    metrics = model.val(
        data=yaml_path,
        split="test",
        project="/runs/detect",
        name="attention_cbam_test",
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

    volume.commit()
    return str(results.save_dir)


@app.local_entrypoint()
def main():
    """Launch CBAM attention training on Modal."""
    print("Starting Run 2 -- YOLO26n + CBAM Attention Training")
    print("   Monitor at: https://modal.com/apps")
    save_dir = train_attention.remote()
    print(f"\nTraining complete!")
    print(f"   Results saved to volume: {save_dir}")
    print(f"\nDownload results with:")
    print(f"   modal volume get ppe-training-vol /runs ./local_runs")
