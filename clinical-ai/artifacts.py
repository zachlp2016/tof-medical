"""Artifact integrity checks shared by provisioning and offline runtime."""
import hashlib
import json
from pathlib import Path

LOCK_PATH = Path(__file__).with_name("models.lock.json")


def read_lock():
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def verified_file(path: Path, metadata: dict) -> bool:
    if not path.is_file() or path.stat().st_size != metadata["size"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == metadata["sha256"]


def verify_bundle(root: Path) -> dict:
    lock = read_lock()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest != lock:
        raise ValueError("Model manifest does not match application lock")
    for operation, model in lock["models"].items():
        for name, metadata in model["files"].items():
            if not verified_file(root / operation / name, metadata):
                raise ValueError("Model artifact verification failed")
    return lock
