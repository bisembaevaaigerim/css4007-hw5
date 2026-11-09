"""Shared helpers: where the data and storage live, and JSON loading."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def load_json(name: str) -> dict:
    """Load one of the supplied fixture files from data/."""
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def storage_dir() -> Path:
    """Directory for live memory (checkpoints + user memory). Ignored by git."""
    path = Path(os.environ.get("HELPDESK_STORAGE_DIR", ROOT / "local-storage"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def ticket_dir() -> Path:
    """Directory where local ticket drafts are written."""
    path = Path(os.environ.get("HELPDESK_TICKET_DIR", ROOT / "outputs" / "tickets"))
    path.mkdir(parents=True, exist_ok=True)
    return path
