"""Loads labeling/.env into os.environ (no dependency on python-dotenv)."""
import os
from pathlib import Path


def load_env(path: Path = Path(__file__).parent / ".env") -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
