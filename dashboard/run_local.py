"""Launch the local dashboard using the project environment when available."""
import os
from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    environment = root / ".venv-dashboard"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if python.is_file() and Path(sys.prefix).resolve() != environment.resolve():
        raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve())], cwd=root))
    from app import app
    app.run(host="127.0.0.1", port=int(os.environ.get("TRINITY_PORT", "5055")), debug=False, threaded=True)
