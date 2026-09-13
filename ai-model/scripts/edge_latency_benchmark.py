"""
Local ONNX latency and quantization benchmark for the Trinity Edge model.

Run:
    python ai-model/scripts/edge_latency_benchmark.py
"""

from __future__ import annotations

import importlib
import platform
import shutil
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AI_MODEL_DIR = SCRIPT_DIR.parent
REPO_ROOT = AI_MODEL_DIR.parent

CONFIG = {
    "model_candidates": [
        AI_MODEL_DIR
        / "outputs"
        / "baseline_yolo26n"
        / "ppe_experiment_package"
        / "exports"
        / "baseline_yolo26n_best.onnx",
        AI_MODEL_DIR / "outputs" / "baseline_yolo26n" / "weights" / "best.onnx",
        AI_MODEL_DIR / "best.onnx",
    ],
    "output_dir": AI_MODEL_DIR / "outputs" / "edge_results",
    "variants_dir": AI_MODEL_DIR / "outputs" / "edge_results" / "onnx_variants",
    "summary_csv": AI_MODEL_DIR
    / "outputs"
    / "edge_results"
    / "latency_quantization_summary.csv",
    "image_size": 640,
    "batch_size": 1,
    "warmup_runs": 5,
    "benchmark_runs": 100,
    "seed": 42,
    "validation_image_dirs": [
        REPO_ROOT / "dataset" / "images" / "val",
        REPO_ROOT / "datasets" / "images" / "val",
        AI_MODEL_DIR / "dataset" / "images" / "val",
        AI_MODEL_DIR / "datasets" / "images" / "val",
        AI_MODEL_DIR / "images" / "val",
    ],
    "max_real_images": 100,
}


def version_of(module_name: str) -> str:
    try:
        module = importlib.import_module(module_name)
        return str(getattr(module, "__version__", "installed"))
    except Exception:
        return "not installed"


def print_environment() -> None:
    print("Environment")
    print(f"  Python: {platform.python_version()} ({sys.executable})")
    print(f"  Platform: {platform.platform()}")
    print(f"  numpy: {version_of('numpy')}")
    print(f"  onnxruntime: {version_of('onnxruntime')}")
    print(f"  opencv-python: {version_of('cv2')}")
    print(f"  pandas: {version_of('pandas')}")
    print(f"  onnxconverter-common: {version_of('onnxconverter_common')}")
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        gpu_note = "GPU provider available" if any("CUDA" in p for p in providers) else "CPU only"
        print(f"  ONNXRuntime providers: {providers} ({gpu_note})")
    except Exception as exc:
        print(f"  ONNXRuntime providers: unavailable ({exc})")
    print()


def require_dependencies():
    missing = []
    modules = {}
    for module_name in ["numpy", "pandas", "onnxruntime"]:
        try:
            modules[module_name] = importlib.import_module(module_name)
        except Exception:
            missing.append(module_name)

    if missing:
        print("ERROR: Missing required dependencies:")
        for name in missing:
            print(f"  - {name}")
        print("Install the edge dependencies and rerun this script.")
        sys.exit(1)

    return modules["numpy"], modules["pandas"], modules["onnxruntime"]


def find_model_path() -> Path:
    for path in CONFIG["model_candidates"]:
        if path.exists():
            return path

    print("ERROR: baseline_yolo26n ONNX model not found.")
    print("Expected one of:")
    for path in CONFIG["model_candidates"]:
        print(f"  - {path}")
    sys.exit(1)


def discover_validation_images() -> list[Path]:
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for directory in CONFIG["validation_image_dirs"]:
        if directory.exists():
            images = sorted(p for p in directory.iterdir() if p.suffix.lower() in image_exts)
            if images:
                return images[: CONFIG["max_real_images"]]
    return []


def preprocess_image(path: Path, np_module, image_size: int):
    try:
        import cv2
    except Exception:
        return None

    image = cv2.imread(str(path))
    if image is None:
        return None
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = cv2.resize(image, (image_size, image_size), interpolation=cv2.INTER_LINEAR)
    blob = image.astype(np_module.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[None, ...]
    return blob


def load_real_inputs(image_paths: list[Path], np_module) -> list:
    inputs = []
    for path in image_paths:
        blob = preprocess_image(path, np_module, CONFIG["image_size"])
        if blob is not None:
            inputs.append(blob)
    return inputs


def make_dummy_input(np_module, rng):
    return rng.random(
        (
            CONFIG["batch_size"],
            3,
            CONFIG["image_size"],
            CONFIG["image_size"],
        ),
        dtype=np_module.float32,
    )


def create_fp16_variant(fp32_path: Path, fp16_path: Path) -> tuple[Path | None, str]:
    try:
        import onnx
        from onnxconverter_common.float16 import convert_float_to_float16
    except Exception as exc:
        return None, f"skipped: FP16 conversion dependency unavailable ({exc})"

    try:
        model = onnx.load(str(fp32_path))
        model_fp16 = convert_float_to_float16(model, keep_io_types=True)
        onnx.save(model_fp16, str(fp16_path))
        return fp16_path, "created with onnxconverter_common.float16"
    except Exception as exc:
        return None, f"skipped: FP16 conversion failed ({exc})"


def create_int8_variant(fp32_path: Path, int8_path: Path) -> tuple[Path | None, str]:
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except Exception as exc:
        return None, f"skipped: ONNXRuntime quantization unavailable ({exc})"

    try:
        quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
        return int8_path, "created with onnxruntime.quantization.quantize_dynamic"
    except Exception as exc:
        return None, f"skipped: INT8 dynamic quantization failed ({exc})"


def benchmark_variant(path: Path, inputs: list, np_module, ort_module) -> tuple[float | None, float | None, str]:
    try:
        session = ort_module.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
    except Exception as exc:
        return None, None, f"inference session failed: {exc}"

    rng = np_module.random.default_rng(CONFIG["seed"])

    try:
        for idx in range(CONFIG["warmup_runs"]):
            blob = inputs[idx % len(inputs)] if inputs else make_dummy_input(np_module, rng)
            session.run(None, {input_name: blob})

        start = time.perf_counter()
        for idx in range(CONFIG["benchmark_runs"]):
            blob = inputs[idx % len(inputs)] if inputs else make_dummy_input(np_module, rng)
            session.run(None, {input_name: blob})
        elapsed = time.perf_counter() - start
    except Exception as exc:
        return None, None, f"inference failed: {exc}"

    latency_ms = (elapsed / CONFIG["benchmark_runs"]) * 1000.0
    fps = 1000.0 / latency_ms if latency_ms > 0 else None
    source_note = "real validation images" if inputs else "deterministic dummy images"
    return latency_ms, fps, f"benchmarked on CPU with {source_note}"


def print_table(rows: list[dict]) -> None:
    headers = ["variant", "batch_size", "model_size_mb", "latency_ms_per_img", "fps", "notes"]
    display_rows = []
    for row in rows:
        display_rows.append(
            {
                "variant": row["variant"],
                "batch_size": row["batch_size"],
                "model_size_mb": "" if row["model_size_mb"] is None else f"{row['model_size_mb']:.2f}",
                "latency_ms_per_img": ""
                if row["latency_ms_per_img"] is None
                else f"{row['latency_ms_per_img']:.2f}",
                "fps": "" if row["fps"] is None else f"{row['fps']:.2f}",
                "notes": row["notes"],
            }
        )

    widths = {
        header: max(len(header), *(len(str(row[header])) for row in display_rows))
        for header in headers
    }
    print("Latency and Quantization Summary")
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in display_rows:
        print(" | ".join(str(row[header]).ljust(widths[header]) for header in headers))
    print()


def main() -> int:
    print_environment()
    np_module, pd_module, ort_module = require_dependencies()

    model_path = find_model_path()
    CONFIG["output_dir"].mkdir(parents=True, exist_ok=True)
    CONFIG["variants_dir"].mkdir(parents=True, exist_ok=True)

    fp32_path = CONFIG["variants_dir"] / "baseline_yolo26n_fp32.onnx"
    shutil.copy2(model_path, fp32_path)

    image_paths = discover_validation_images()
    inputs = load_real_inputs(image_paths, np_module) if image_paths else []
    if inputs:
        print(f"Using {len(inputs)} validation images for latency inputs.")
    else:
        print("No local validation images found; using deterministic dummy images.")
    print(f"Selected FP32 model: {model_path}")
    print(f"Variant output directory: {CONFIG['variants_dir']}")
    print()

    variant_specs = [
        ("FP32", fp32_path, "baseline ONNX copied from selected deployment model"),
    ]

    fp16_path, fp16_note = create_fp16_variant(fp32_path, CONFIG["variants_dir"] / "baseline_yolo26n_fp16.onnx")
    if fp16_path is not None:
        variant_specs.append(("FP16", fp16_path, fp16_note))
    else:
        print(f"WARNING: FP16 {fp16_note}")

    int8_path, int8_note = create_int8_variant(fp32_path, CONFIG["variants_dir"] / "baseline_yolo26n_int8.onnx")
    if int8_path is not None:
        variant_specs.append(("INT8", int8_path, int8_note))
    else:
        print(f"WARNING: INT8 {int8_note}")
    print()

    rows = []
    for variant, path, note in variant_specs:
        print(f"Benchmarking {variant}: {path.name}")
        latency_ms, fps, bench_note = benchmark_variant(path, inputs, np_module, ort_module)
        notes = f"{note}; {bench_note}"
        rows.append(
            {
                "variant": variant,
                "batch_size": CONFIG["batch_size"],
                "model_size_mb": path.stat().st_size / (1024 * 1024) if path.exists() else None,
                "latency_ms_per_img": latency_ms,
                "fps": fps,
                "notes": notes,
            }
        )

    summary_df = pd_module.DataFrame(
        rows,
        columns=[
            "variant",
            "batch_size",
            "model_size_mb",
            "latency_ms_per_img",
            "fps",
            "notes",
        ],
    )
    summary_df.to_csv(CONFIG["summary_csv"], index=False)

    print_table(rows)
    print(f"DONE - results saved to {CONFIG['summary_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
