import os
import sys
import tempfile
from pathlib import Path

os.environ["RUNTIME_PATH"] = str(Path(tempfile.mkdtemp()) / "runtime.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
