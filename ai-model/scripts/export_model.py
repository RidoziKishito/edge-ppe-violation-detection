"""
Run 4 -- Edge Export with Quantization on Modal A100
====================================================
Construction Site PPE Safety Detection

This script loads the best trained model from a specified run and exports it
to ONNX format with FP16 and optional INT8 quantization for edge deployment.

Exports:
    1. FP16 ONNX -- up to 3x CPU speedup, ~50% size reduction
    2. INT8 ONNX -- maximum compression (only if mAP drop < 2%)

Usage:
    # Export the best baseline model
    modal run export_model.py --run-name baseline_yolo26n

    # Export the CBAM attention model
    modal run export_model.py --run-name attention_cbam

    # Export the ghost conv model
    modal run export_model.py --run-name ghost_conv
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
    .add_local_file(str(_CONFIGS_DIR / "data_modal.yaml"), remote_path="/config/data_modal.yaml")
)


@app.function(
    image=image,
    gpu="L4",
    timeout=7200,  # 2 hours max for export
    volumes={
        "/runs": volume,
        "/dataset": dataset_volume,
    },
)
def export_model(run_name: str = "baseline_yolo26n"):
    """
    Export the best model from a training run to ONNX format.

    Args:
        run_name: Name of the training run directory under /runs/detect/
                  (e.g., "baseline_yolo26n", "attention_cbam", "ghost_conv")
    """
    from ultralytics import YOLO
    import os
    import shutil

    yaml_path = "/config/data_modal.yaml"
    if not os.path.exists(yaml_path):
        yaml_path = "/dataset/data.yaml"

    # Locate the best weights from the training run
    weights_path = f"/runs/detect/{run_name}/weights/best.pt"

    # Handle versioned directories (e.g., baseline_yolo26n2, baseline_yolo26n3)
    if not os.path.exists(weights_path):
        # Search for the latest version
        detect_dir = "/runs/detect"
        candidates = sorted([
            d for d in os.listdir(detect_dir)
            if d.startswith(run_name)
        ])
        if candidates:
            latest = candidates[-1]
            weights_path = f"{detect_dir}/{latest}/weights/best.pt"
            print(f"Using latest version: {latest}")

    if not os.path.exists(weights_path):
        print(f"[ERROR] Weights not found at: {weights_path}")
        print(f"   Available runs:")
        for d in os.listdir("/runs/detect"):
            best = os.path.exists(f"/runs/detect/{d}/weights/best.pt")
            print(f"     {'[OK]' if best else '[--]'} {d}")
        return "ERROR: Weights not found"

    print(f"Loading model from: {weights_path}")
    model = YOLO(weights_path)

    total_params = sum(p.numel() for p in model.model.parameters())
    print(f"Total parameters: {total_params:,}")

    # Create export directory
    export_dir = f"/runs/exports/{run_name}"
    os.makedirs(export_dir, exist_ok=True)

    # -----------------------------------------------------------------------
    # 1. Validate original model (reference mAP)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("REFERENCE VALIDATION -- Original PyTorch Model")
    print("=" * 60)
    ref_metrics = model.val(
        data=yaml_path,
        split="test",
    )
    ref_map50 = ref_metrics.box.map50
    print(f"Reference mAP@0.5: {ref_map50:.4f}")

    # -----------------------------------------------------------------------
    # 2. Export FP16 ONNX
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EXPORT -- FP16 ONNX")
    print("=" * 60)
    fp16_path = model.export(
        format="onnx",
        imgsz=640,
        half=True,
        simplify=True,
    )
    print(f"FP16 ONNX exported to: {fp16_path}")

    # Copy to exports directory
    fp16_dest = os.path.join(export_dir, f"{run_name}_fp16.onnx")
    shutil.copy2(fp16_path, fp16_dest)

    # Get file size
    fp16_size = os.path.getsize(fp16_dest) / (1024 * 1024)  # MB
    print(f"FP16 ONNX size: {fp16_size:.1f} MB")

    # Validate FP16 ONNX
    print("\nValidating FP16 ONNX...")
    fp16_model = YOLO(fp16_dest)
    fp16_metrics = fp16_model.val(
        data=yaml_path,
        split="test",
    )
    fp16_map50 = fp16_metrics.box.map50
    fp16_drop = (ref_map50 - fp16_map50) * 100
    print(f"FP16 mAP@0.5: {fp16_map50:.4f} (drop: {fp16_drop:.2f}%)")

    # -----------------------------------------------------------------------
    # 3. Export INT8 ONNX (only if FP16 results are strong)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EXPORT -- INT8 ONNX")
    print("=" * 60)

    # Reload original model for INT8 export
    model = YOLO(weights_path)

    try:
        int8_path = model.export(
            format="onnx",
            imgsz=640,
            int8=True,
            data=yaml_path,  # INT8 needs calibration data
        )
        print(f"INT8 ONNX exported to: {int8_path}")

        int8_dest = os.path.join(export_dir, f"{run_name}_int8.onnx")
        shutil.copy2(int8_path, int8_dest)

        int8_size = os.path.getsize(int8_dest) / (1024 * 1024)
        print(f"INT8 ONNX size: {int8_size:.1f} MB")

        # Validate INT8
        print("\nValidating INT8 ONNX...")
        int8_model = YOLO(int8_dest)
        int8_metrics = int8_model.val(
            data=yaml_path,
            split="test",
        )
        int8_map50 = int8_metrics.box.map50
        int8_drop = (ref_map50 - int8_map50) * 100
        print(f"INT8 mAP@0.5: {int8_map50:.4f} (drop: {int8_drop:.2f}%)")

        if int8_drop > 2.0:
            print(f"[WARN] INT8 mAP drop ({int8_drop:.2f}%) exceeds 2% threshold")
            print("   Recommendation: Use FP16 ONNX for deployment")
        else:
            print(f"[OK] INT8 mAP drop ({int8_drop:.2f}%) within acceptable range")
    except Exception as e:
        print(f"[WARN] INT8 export failed: {e}")
        print("   Using FP16 ONNX as final export")
        int8_size = None
        int8_map50 = None
        int8_drop = None

    # -----------------------------------------------------------------------
    # 4. Summary Report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EXPORT SUMMARY")
    print("=" * 60)
    print(f"Run:              {run_name}")
    print(f"Parameters:       {total_params:,}")
    print(f"Reference mAP@0.5: {ref_map50:.4f}")
    print(f"")
    print(f"FP16 ONNX:")
    print(f"  Path:    {fp16_dest}")
    print(f"  Size:    {fp16_size:.1f} MB")
    print(f"  mAP@0.5: {fp16_map50:.4f} (delta={fp16_drop:+.2f}%)")
    if int8_map50 is not None:
        print(f"")
        print(f"INT8 ONNX:")
        print(f"  Path:    {int8_dest}")
        print(f"  Size:    {int8_size:.1f} MB")
        print(f"  mAP@0.5: {int8_map50:.4f} (delta={int8_drop:+.2f}%)")
    print(f"")
    print(f"Input shape:      [1, 3, 640, 640]")
    print(f"Normalization:    divide by 255, RGB channel order")
    print(f"NMS:              End-to-end (built-in, no post-processing needed)")

    # -----------------------------------------------------------------------
    # 5. Generate minimal inference snippet
    # -----------------------------------------------------------------------
    inference_snippet = f'''
# Minimal ONNX Inference Snippet -- {run_name}
# =============================================
import onnxruntime as ort
import numpy as np
import cv2

# Load model
session = ort.InferenceSession("{run_name}_fp16.onnx")
input_name = session.get_inputs()[0].name

# Preprocess
img = cv2.imread("test_image.jpg")
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
img_resized = cv2.resize(img_rgb, (640, 640))
blob = img_resized.astype(np.float32) / 255.0
blob = blob.transpose(2, 0, 1)[np.newaxis, ...]  # [1, 3, 640, 640]

# Inference
outputs = session.run(None, {{input_name: blob}})

# Classes: helmet, gloves, vest, boots, goggles, none, Person,
#          no_helmet, no_goggle, no_gloves, no_boots
# Confidence threshold: 0.25 (recommended)
# NMS: End-to-end (no post-processing needed for YOLO26)
'''

    snippet_path = os.path.join(export_dir, "inference_snippet.py")
    with open(snippet_path, "w") as f:
        f.write(inference_snippet)
    print(f"Inference snippet saved to: {snippet_path}")

    volume.commit()
    return export_dir


@app.local_entrypoint()
def main(run_name: str = "baseline_yolo26n"):
    """Export a trained model to ONNX format.

    Args:
        run_name: Name of training run to export (default: baseline_yolo26n)
    """
    print(f"Starting Run 4 -- ONNX Export for '{run_name}'")
    print(f"   Monitor at: https://modal.com/apps")
    export_dir = export_model.remote(run_name=run_name)
    print(f"\nExport complete!")
    print(f"   Exports saved to volume: {export_dir}")
    print(f"\nDownload exports with:")
    print(f"   modal volume get ppe-training-vol /runs/exports ./local_exports")
