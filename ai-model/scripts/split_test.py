"""
split_test.py -- Add more images to the test set from train
===========================================================

Moves (not copies) ~10% of images from train to test.
Uses stratified sampling to ensure violation classes (IDs 7-10) are
proportionally represented in the new test set.
Does not touch existing test images.

Usage:
    python split_test.py
    python split_test.py --dataset ../data/merged-ppe
"""

import argparse
import os
import random
import shutil
from collections import defaultdict
from pathlib import Path


VIOLATION_CLASSES = {7, 8, 9, 10}
CLASS_NAMES = {
    0: "helmet", 1: "gloves", 2: "vest", 3: "boots", 4: "goggles",
    5: "none", 6: "Person",
    7: "no_helmet", 8: "no_goggle", 9: "no_gloves", 10: "no_boots"
}


def parse_label_file(label_path: Path) -> set[int]:
    """Return set of unique class IDs from a YOLO label file."""
    classes = set()
    if not label_path.exists():
        return classes
    text = label_path.read_text().strip()
    if not text:
        return classes
    for line in text.splitlines():
        parts = line.strip().split()
        if parts:
            try:
                classes.add(int(parts[0]))
            except ValueError:
                pass
    return classes


def count_violation_classes(img_paths, lbl_dir: Path):
    """Count how many images contain each violation class."""
    counts = {c: 0 for c in VIOLATION_CLASSES}
    for img_path in img_paths:
        lbl_path = lbl_dir / (img_path.stem + ".txt")
        classes = parse_label_file(lbl_path)
        for c in VIOLATION_CLASSES:
            if c in classes:
                counts[c] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description="Move ~10% of train to test, prioritizing violations.")
    parser.add_argument("--dataset", type=str, default="../data/merged-ppe", help="Path to dataset root")
    parser.add_argument("--ratio", type=float, default=0.10, help="Fraction to move")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default: True)")
    parser.add_argument("--execute", action="store_false", dest="dry_run", help="Actually move the files")
    args = parser.parse_args()

    random.seed(args.seed)
    dataset = Path(args.dataset)
    DRY_RUN = args.dry_run

    train_img_dir = dataset / "images" / "train"
    train_lbl_dir = dataset / "labels" / "train"
    test_img_dir = dataset / "images" / "test"
    test_lbl_dir = dataset / "labels" / "test"

    if not train_img_dir.exists() or not train_lbl_dir.exists():
        print(f"[ERROR] Train directories not found in {dataset.resolve()}")
        return

    test_img_dir.mkdir(parents=True, exist_ok=True)
    test_lbl_dir.mkdir(parents=True, exist_ok=True)

    print(f"Dataset root: {dataset.resolve()}")
    print(f"Dry run:      {'ON' if DRY_RUN else 'OFF'}")

    # Gather existing test images count
    img_extensions = {".jpg", ".jpeg", ".png"}
    existing_test_imgs = [f for f in test_img_dir.iterdir() if f.suffix.lower() in img_extensions]
    
    # Gather train images
    train_imgs = sorted([f for f in train_img_dir.iterdir() if f.suffix.lower() in img_extensions])
    
    print(f"\n[BEFORE]")
    print(f"Total Train Images: {len(train_imgs)}")
    print(f"Total Test Images:  {len(existing_test_imgs)}")
    
    before_test_counts = count_violation_classes(existing_test_imgs, test_lbl_dir)
    print("Test Set Violation Class Image Counts:")
    for c in VIOLATION_CLASSES:
        print(f"  {CLASS_NAMES[c]} (ID {c}): {before_test_counts[c]}")

    # Categorize train images
    violation_buckets = {c: [] for c in VIOLATION_CLASSES}
    non_violation_bucket = []
    
    missing_labels = 0
    for img_path in train_imgs:
        lbl_path = train_lbl_dir / (img_path.stem + ".txt")
        if not lbl_path.exists():
            missing_labels += 1
            continue
            
        classes = parse_label_file(lbl_path)
        present_violations = classes.intersection(VIOLATION_CLASSES)
        
        if present_violations:
            rarest = max(present_violations)
            violation_buckets[rarest].append(img_path)
        else:
            non_violation_bucket.append(img_path)

    if missing_labels > 0:
        print(f"[WARN] Skipped {missing_labels} images with missing labels.")

    # Sample 10% from each bucket
    to_move = []
    
    for c in sorted(VIOLATION_CLASSES, reverse=True):
        bucket = violation_buckets[c]
        random.shuffle(bucket)
        n_move = int(len(bucket) * args.ratio)
        if len(bucket) > 0 and n_move == 0:
            n_move = 1 
        to_move.extend(bucket[:n_move])
        
    random.shuffle(non_violation_bucket)
    n_move_non_violation = int(len(non_violation_bucket) * args.ratio)
    to_move.extend(non_violation_bucket[:n_move_non_violation])

    print(f"\nSelected {len(to_move)} images to move to test set.")

    if DRY_RUN:
        print("\n[DRY RUN] Would move the following images (showing first 10):")
        for img in to_move[:10]:
            print(f"  {img.name}")
        if len(to_move) > 10:
            print(f"  ... and {len(to_move) - 10} more.")
    else:
        moved_count = 0
        skip_count = 0
        for img_path in to_move:
            dest_img = test_img_dir / img_path.name
            if dest_img.exists():
                skip_count += 1
                continue
                
            lbl_name = img_path.stem + ".txt"
            src_lbl = train_lbl_dir / lbl_name
            dest_lbl = test_lbl_dir / lbl_name
            
            if dest_lbl.exists():
                skip_count += 1
                continue

            shutil.move(str(img_path), str(dest_img))
            if src_lbl.exists():
                shutil.move(str(src_lbl), str(dest_lbl))
            
            moved_count += 1
            
        print(f"\n[MOVE] Successfully moved {moved_count} images and labels.")
        if skip_count > 0:
            print(f"[MOVE] Skipped {skip_count} files that already existed.")

    # Calculate [AFTER] stats
    after_train_count = len(train_imgs) - len(to_move) if DRY_RUN else len([f for f in train_img_dir.iterdir() if f.suffix.lower() in img_extensions])
    after_test_count = len(existing_test_imgs) + len(to_move) if DRY_RUN else len([f for f in test_img_dir.iterdir() if f.suffix.lower() in img_extensions])
    
    print(f"\n[AFTER] {'(Simulated)' if DRY_RUN else '(Actual)'}")
    print(f"Total Train Images: {after_train_count}")
    print(f"Total Test Images:  {after_test_count}")
    
    if DRY_RUN:
        simulated_counts = {c: before_test_counts[c] for c in VIOLATION_CLASSES}
        for img_path in to_move:
            lbl_path = train_lbl_dir / (img_path.stem + ".txt")
            classes = parse_label_file(lbl_path)
            for c in VIOLATION_CLASSES:
                if c in classes:
                    simulated_counts[c] += 1
        print("Test Set Violation Class Image Counts:")
        for c in VIOLATION_CLASSES:
            print(f"  {CLASS_NAMES[c]} (ID {c}): {simulated_counts[c]}")
    else:
        after_test_imgs = [f for f in test_img_dir.iterdir() if f.suffix.lower() in img_extensions]
        after_test_counts = count_violation_classes(after_test_imgs, test_lbl_dir)
        print("Test Set Violation Class Image Counts:")
        for c in VIOLATION_CLASSES:
            print(f"  {CLASS_NAMES[c]} (ID {c}): {after_test_counts[c]}")

    if DRY_RUN:
        print("\nRun with --execute to actually perform the move operation.")

if __name__ == "__main__":
    main()
