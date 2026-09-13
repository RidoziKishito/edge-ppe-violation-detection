import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2


def extract_first_frame(source: Path, output_path: Path) -> tuple[int, int]:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {source}")

    try:
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Could not read the first frame from: {source}")
        height, width = frame.shape[:2]
        if not cv2.imwrite(str(output_path), frame):
            raise RuntimeError(f"Could not write preview frame: {output_path}")
        return width, height
    finally:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a preview frame and create a zone profile for a video."
    )
    parser.add_argument("--source", required=True, help="Video file path")
    parser.add_argument(
        "--output",
        help="Zone profile path (default: configs/zones/<video-name>.json)",
    )
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()

    if not source.is_file():
        parser.error(f"Video file does not exist: {source}")

    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else Path("configs/zones").resolve() / f"{source.stem}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    preview_path = Path(tempfile.gettempdir()) / f"trinity_zone_preview_{source.stem}.jpg"
    try:
        width, height = extract_first_frame(source, preview_path)
        print(f"Video resolution: {width}x{height}")
        print(f"Opening zone editor for: {source.name}")
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW
            
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("zone_editor.py")),
                str(preview_path),
                "--output",
                str(output),
                "--source",
                source.name,
                "--width",
                str(width),
                "--height",
                str(height),
            ],
            check=False,
            creationflags=creation_flags,
        )
        return result.returncode
    finally:
        preview_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
