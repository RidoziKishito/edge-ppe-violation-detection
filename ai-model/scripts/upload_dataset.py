"""
Upload Dataset to Modal Volume
===============================
Uploads the local merged-ppe dataset to a persistent Modal Volume so that
training scripts can mount it instantly without re-uploading every run.

This only needs to be run ONCE (or whenever the dataset changes).

Usage:
    modal run upload_dataset.py
"""

import modal
import os
from pathlib import Path

app = modal.App("ppe-dataset-upload")

# Resolve paths relative to this script, not CWD
_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_DIR = _SCRIPT_DIR.parent / "data" / "merged-ppe"

# Persistent volume for the dataset -- shared across all training runs
dataset_volume = modal.Volume.from_name("ppe-dataset-vol", create_if_missing=True)

# Minimal image -- only needs Python to copy files
image = (
    modal.Image.debian_slim(python_version="3.11")
    .add_local_dir(str(_DATA_DIR), remote_path="/local_dataset")
)


@app.function(
    image=image,
    volumes={"/dataset": dataset_volume},
    timeout=3600,  # 1 hour for large uploads
)
def upload():
    """
    Copy the dataset from the container image into the persistent volume.

    The dataset is first baked into the container image via add_local_dir,
    then copied to the volume. This way the volume persists across runs
    and training scripts only need to mount the volume (instant, no upload).
    """
    import shutil

    src = "/local_dataset"
    dst = "/dataset"

    # Show what we're uploading
    for split in ["train", "val", "test"]:
        img_dir = os.path.join(src, "images", split)
        lbl_dir = os.path.join(src, "labels", split)
        if os.path.exists(img_dir):
            n_imgs = len(os.listdir(img_dir))
            n_lbls = len(os.listdir(lbl_dir)) if os.path.exists(lbl_dir) else 0
            print(f"  {split}: {n_imgs} images, {n_lbls} labels")
        else:
            print(f"  {split}: NOT FOUND")

    # Copy images
    for split in ["train", "val", "test"]:
        for subdir in ["images", "labels"]:
            src_dir = os.path.join(src, subdir, split)
            dst_dir = os.path.join(dst, subdir, split)

            if not os.path.exists(src_dir):
                print(f"[WARN] Skipping {src_dir} (not found)")
                continue

            os.makedirs(dst_dir, exist_ok=True)
            files = os.listdir(src_dir)
            print(f"Copying {len(files)} files: {subdir}/{split} ...")

            for f in files:
                shutil.copy2(os.path.join(src_dir, f), os.path.join(dst_dir, f))

    # Also copy data.yaml if it exists
    src_yaml = os.path.join(src, "data.yaml")
    if os.path.exists(src_yaml):
        shutil.copy2(src_yaml, os.path.join(dst, "data.yaml"))
        print("Copied data.yaml")

    # Commit changes to volume
    dataset_volume.commit()
    print("\n[OK] Dataset uploaded to volume 'ppe-dataset-vol'")

    # Verify
    print("\nVolume contents verification:")
    for split in ["train", "val", "test"]:
        img_dir = os.path.join(dst, "images", split)
        lbl_dir = os.path.join(dst, "labels", split)
        n_imgs = len(os.listdir(img_dir)) if os.path.exists(img_dir) else 0
        n_lbls = len(os.listdir(lbl_dir)) if os.path.exists(lbl_dir) else 0
        print(f"  {split}: {n_imgs} images, {n_lbls} labels")


@app.local_entrypoint()
def main():
    """Upload the merged-ppe dataset to Modal Volume."""
    print("Uploading dataset to Modal Volume 'ppe-dataset-vol'...")
    print("   This only needs to be done once (or when dataset changes).")
    print()
    upload.remote()
    print("\nDone! Training scripts will now mount this volume instantly.")
