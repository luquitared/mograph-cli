# TODO: pipeline.py and cloudrun/server.py should import from here
"""Shared .env file loader."""
import os
from pathlib import Path


def load_env_file(env_path: Path = None) -> None:
    """Load environment variables from .env file if present.

    Only sets variables that aren't already in the environment.
    """
    if env_path is None:
        env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
