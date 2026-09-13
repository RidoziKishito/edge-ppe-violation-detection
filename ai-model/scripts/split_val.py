"""
split_val.py -- Create a stratified validation set from training data
====================================================================

Copies 10% of train/ images+labels into val/ (overwriting existing val/),
stratified by the rarest class present in each image so that
underrepresented classes (no_boots, no_goggle, etc.) are fairly
represented in validation.

Train/ is NOT modified -- images are COPIED, not moved.
Test/ is not touched.

Usage:
    python split_val.py
    python split_val.py --dataset ./data/merged-ppe
    python split_val.py --dataset ./data/merged-ppe --ratio 0.15
"""

import argparse
import os
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path


# Class names matching data_modal.yaml
CLASS_NAMES = {
    0: "helmet",
    1: "gloves",
    2: "vest",
    3: "boots",
    4: "goggles",
    5: "none",
    6: "Person",
    7: "no_helmet",
    8: "no_goggle",
    9: "no_gloves",
    10: "no_boots",
}


def parse_label_file(label_path: Path) -> list[int]:
    """Return list of class IDs from a YOLO label file."""
    classes = []
    if not label_path.exists():
        return classes
    text = label_path.read_text().strip()
    if not text:
        return classes
    for line in text.splitlines():
        parts = line.strip().split()
        if parts:
            classes.append(int(parts[0]))
    return classes


def count_instances(label_dir: Path) -> Counter:
    """Count total instances per class across all label files in a directory."""
    counter = Counter()
    if not label_dir.exists():
        return counter
    for lbl_file in sorted(label_dir.glob("*.txt")):
        classes = parse_label_file(lbl_file)
        counter.update(classes)
    return counter


def print_class_counts(counter: Counter, title: str):
    """Pretty-print per-class instance counts."""
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")
    print(f"  {'ID':>3}  {'Class':<12}  {'Instances':>10}")
    print(f"  {'-' * 3}  {'-' * 12}  {'-' * 10}")
    total = 0
    for cls_id in sorted(CLASS_NAMES.keys()):
        name = CLASS_NAMES[cls_id]
        cnt = counter.get(cls_id, 0)
        total += cnt
        flag = " [!]" if cnt < 100 else ""
        print(f"  {cls_id:>3}  {name:<12}  {cnt:>10,}{flag}")
    print(f"  {'':>3}  {'TOTAL':<12}  {total:>10,}")
    print(f"{'=' * 55}")


def main():
    parser = argparse.ArgumentParser(
        description="Create stratified val split from training data."
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="../data/merged-ppe",
        help="Path to dataset root (contains images/ and labels/ dirs)",
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=0.10,
        help="Fraction of train to use for val (default: 0.10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    dataset = Path(args.dataset)

    train_img_dir = dataset / "images" / "train"
    train_lbl_dir = dataset / "labels" / "train"
    val_img_dir = dataset / "images" / "val"
    val_lbl_dir = dataset / "labels" / "val"

    assert train_img_dir.exists(), f"Train images not found: {train_img_dir}"
    assert train_lbl_dir.exists(), f"Train labels not found: {train_lbl_dir}"

    # -----------------------------------------------------------------------
    # 1. Gather all training images and their classes
    # -----------------------------------------------------------------------
    print(f"Dataset root: {dataset.resolve()}")
    print(f"Val ratio:    {args.ratio:.0%}")
    print(f"Seed:         {args.seed}")

    img_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    all_images = sorted([
        f for f in train_img_dir.iterdir()
        if f.suffix.lower() in img_extensions
    ])
    print(f"\nTotal train images found: {len(all_images):,}")

    # Parse labels for each image, skip background (empty/missing labels)
    image_classes: dict[Path, list[int]] = {}
    skipped = 0
    for img_path in all_images:
        lbl_path = train_lbl_dir / (img_path.stem + ".txt")
        classes = parse_label_file(lbl_path)
        if not classes:
            skipped += 1
            continue
        image_classes[img_path] = classes

    print(f"Skipped background images (no labels): {skipped:,}")
    print(f"Images with annotations: {len(image_classes):,}")

    # -----------------------------------------------------------------------
    # 2. Count global class frequencies to find rarest class per image
    # -----------------------------------------------------------------------
    global_counts = Counter()
    for classes in image_classes.values():
        global_counts.update(classes)

    print_class_counts(global_counts, "BEFORE SPLIT -- Train class instances")

    # Assign each image to a stratum based on its RAREST class
    # (the class with the lowest global frequency present in that image)
    image_strata: dict[int, list[Path]] = defaultdict(list)
    for img_path, classes in image_classes.items():
        unique_classes = set(classes)
        rarest_class = min(unique_classes, key=lambda c: global_counts.get(c, 0))
        image_strata[rarest_class].append(img_path)

    print(f"\nStratification groups (by rarest class in image):")
    for cls_id in sorted(image_strata.keys()):
        name = CLASS_NAMES.get(cls_id, f"cls_{cls_id}")
        print(f"   {cls_id:>2} ({name:<12}): {len(image_strata[cls_id]):>6,} images")

    # -----------------------------------------------------------------------
    # 3. Sample val set from each stratum
    # -----------------------------------------------------------------------
    val_images: list[Path] = []
    for cls_id in sorted(image_strata.keys()):
        images = image_strata[cls_id]
        random.shuffle(images)
        n_val = max(1, int(len(images) * args.ratio))  # At least 1 per stratum
        val_images.extend(images[:n_val])

    print(f"\nSelected {len(val_images):,} images for validation")

    # -----------------------------------------------------------------------
    # 4. Clear existing val/ and copy selected images + labels
    # -----------------------------------------------------------------------
    # Overwrite val directories
    if val_img_dir.exists():
        shutil.rmtree(val_img_dir)
    if val_lbl_dir.exists():
        shutil.rmtree(val_lbl_dir)
    val_img_dir.mkdir(parents=True, exist_ok=True)
    val_lbl_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for img_path in val_images:
        # Copy image
        shutil.copy2(img_path, val_img_dir / img_path.name)

        # Copy label
        lbl_name = img_path.stem + ".txt"
        lbl_src = train_lbl_dir / lbl_name
        if lbl_src.exists():
            shutil.copy2(lbl_src, val_lbl_dir / lbl_name)

        copied += 1

    print(f"Copied {copied:,} images + labels to val/")

    # -----------------------------------------------------------------------
    # 5. Print final counts
    # -----------------------------------------------------------------------
    train_counts = count_instances(train_lbl_dir)
    val_counts = count_instances(val_lbl_dir)

    print_class_counts(train_counts, "AFTER SPLIT -- Train class instances (unchanged)")
    print_class_counts(val_counts, "AFTER SPLIT -- Val class instances (new)")

    # Summary
    print(f"\nSummary:")
    print(f"   Train images: {len(list(train_img_dir.iterdir())):>7,} (unchanged)")
    print(f"   Val images:   {len(list(val_img_dir.iterdir())):>7,} (new)")
    test_img_dir = dataset / "images" / "test"
    if test_img_dir.exists():
        print(f"   Test images:  {len(list(test_img_dir.iterdir())):>7,} (untouched)")
    print(f"\nDone! Re-upload to Modal volume with: modal run upload_dataset.py")


if __name__ == "__main__":
    main()
