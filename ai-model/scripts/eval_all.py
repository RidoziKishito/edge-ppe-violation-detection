"""
Eval All -- Re-evaluate 3 trained models on new test set
=========================================================
Loads best.pt from each training run stored in ppe-training-vol,
then runs model.val(split="test") against the updated test set
in ppe-dataset-vol (3,154 images after re-split).

Usage:
    modal run eval_all.py
"""

import modal
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONFIGS_DIR = _SCRIPT_DIR.parent / "configs"

app = modal.App("ppe-eval-all")

volume        = modal.Volume.from_name("ppe-training-vol")
dataset_volume = modal.Volume.from_name("ppe-dataset-vol")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0", "libglib2.0-dev")
    .pip_install(
        "ultralytics>=8.4.0",
        "torch",
        "torchvision",
    )
    .add_local_file(str(_CONFIGS_DIR / "data_modal.yaml"), remote_path="/config/data_modal.yaml")
)

RUNS = [
    {
        "name":     "baseline_yolo26n",
        "weights":  "/runs/detect/baseline_yolo26n/weights/best.pt",
        "out_name": "eval_baseline_v2",
    },
    {
        "name":     "attention_cbam",
        "weights":  "/runs/detect/attention_cbam/weights/best.pt",
        "out_name": "eval_cbam_v2",
    },
    {
        "name":     "ghost_conv",
        "weights":  "/runs/detect/ghost_conv/weights/best.pt",
        "out_name": "eval_ghost_v2",
    },
]


@app.function(
    image=image,
    gpu="L4",
    timeout=3600,
    volumes={
        "/runs":    volume,
        "/dataset": dataset_volume,
    },
)
def eval_all():
    from ultralytics import YOLO
    import os

    yaml_path = "/config/data_modal.yaml"
    if not os.path.exists(yaml_path):
        yaml_path = "/dataset/data.yaml"

    # Verify test set size
    test_img_dir = "/dataset/images/test"
    n_test = len(os.listdir(test_img_dir)) if os.path.exists(test_img_dir) else 0
    print(f"\n{'='*60}")
    print(f"Test set: {n_test} images")
    print(f"Dataset config: {yaml_path}")
    print(f"{'='*60}\n")

    results_summary = []

    for run in RUNS:
        weights = run["weights"]
        print(f"\n{'='*60}")
        print(f"Evaluating: {run['name']}")
        print(f"Weights:    {weights}")
        print(f"{'='*60}")

        if not os.path.exists(weights):
            print(f"[ERROR] Weights not found: {weights}")
            results_summary.append({
                "model": run["name"],
                "error": "weights not found",
            })
            continue

        # For CBAM -- need to register module before loading
        if "cbam" in run["name"]:
            try:
                from ultralytics.nn.modules.conv import CBAM
                import ultralytics.nn.tasks as nn_tasks
                nn_tasks.CBAM = CBAM
            except ImportError:
                print("[WARN] CBAM registration failed, proceeding anyway")

        model = YOLO(weights)

        metrics = model.val(
            data=yaml_path,
            split="test",
            project="/runs/detect",
            name=run["out_name"],
        )

        per_class_map50 = metrics.box.ap50
        class_names     = metrics.names

        # Violation class IDs
        VIOLATION_IDS = {7: "no_helmet", 8: "no_goggle", 9: "no_gloves", 10: "no_boots"}

        print(f"\n--- {run['name']} TEST RESULTS ---")
        print(f"  mAP@0.5      : {metrics.box.map50:.4f}")
        print(f"  mAP@0.5:0.95 : {metrics.box.map:.4f}")
        print(f"  Precision    : {metrics.box.mp:.4f}")
        print(f"  Recall       : {metrics.box.mr:.4f}")
        print(f"  Inference    : {metrics.speed['inference']:.1f}ms/img")
        print(f"\n  Violation class mAP@0.5:")
        for cls_id, cls_name in VIOLATION_IDS.items():
            ap = per_class_map50[cls_id] if cls_id < len(per_class_map50) else -1
            print(f"    [{cls_id}] {cls_name:12s}: {ap:.4f}")

        results_summary.append({
            "model":        run["name"],
            "map50":        metrics.box.map50,
            "map50_95":     metrics.box.map,
            "precision":    metrics.box.mp,
            "recall":       metrics.box.mr,
            "inference_ms": metrics.speed["inference"],
            "no_helmet":    float(per_class_map50[7]) if 7 < len(per_class_map50) else -1,
            "no_goggle":    float(per_class_map50[8]) if 8 < len(per_class_map50) else -1,
            "no_gloves":    float(per_class_map50[9]) if 9 < len(per_class_map50) else -1,
            "no_boots":     float(per_class_map50[10]) if 10 < len(per_class_map50) else -1,
        })

    # Final comparison table
    print(f"\n\n{'='*60}")
    print("FINAL COMPARISON -- ALL MODELS (Test Set v2)")
    print(f"{'='*60}")
    header = f"{'Model':<20} {'mAP50':>7} {'mAP50-95':>9} {'P':>7} {'R':>7} {'ms/img':>8}"
    print(header)
    print("-" * len(header))
    for r in results_summary:
        if "error" in r:
            print(f"{r['model']:<20}  ERROR: {r['error']}")
            continue
        print(
            f"{r['model']:<20} "
            f"{r['map50']:>7.4f} "
            f"{r['map50_95']:>9.4f} "
            f"{r['precision']:>7.4f} "
            f"{r['recall']:>7.4f} "
            f"{r['inference_ms']:>7.1f}ms"
        )

    print(f"\nViolation Classes mAP@0.5:")
    vio_header = f"{'Model':<20} {'no_helmet':>10} {'no_goggle':>10} {'no_gloves':>10} {'no_boots':>10}"
    print(vio_header)
    print("-" * len(vio_header))
    for r in results_summary:
        if "error" in r:
            continue
        print(
            f"{r['model']:<20} "
            f"{r['no_helmet']:>10.4f} "
            f"{r['no_goggle']:>10.4f} "
            f"{r['no_gloves']:>10.4f} "
            f"{r['no_boots']:>10.4f}"
        )

    volume.commit()
    return results_summary


@app.local_entrypoint()
def main():
    print("Re-evaluating all 3 models on test set v2 (3,154 images)...")
    print("  Monitor at: https://modal.com/apps")
    results = eval_all.remote()
    print(f"\nDone! Results saved to ppe-training-vol:/runs/detect/eval_*_v2/")