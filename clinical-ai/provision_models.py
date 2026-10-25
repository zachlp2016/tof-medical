"""Explicit online provisioning. Runtime never invokes this script."""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from artifacts import read_lock, verified_file, verify_bundle


def provision(root: Path):
    lock = read_lock()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o755)
    # Mark an interrupted replacement unready until every locked file verifies.
    (root / "manifest.json").unlink(missing_ok=True)
    for operation, model in lock["models"].items():
        directory = root / operation
        directory.mkdir(exist_ok=True)
        os.chmod(directory, 0o755)
        for name, metadata in model["files"].items():
            destination = directory / name
            if verified_file(destination, metadata):
                os.chmod(destination, 0o644)
                continue
            url = f"https://huggingface.co/{model['id']}/resolve/{model['revision']}/{name}"
            temporary = destination.with_name(name + ".partial")
            request = urllib.request.Request(url, headers={"User-Agent": "TOF-Clinical-Model-Provisioner/1"})
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                remaining = metadata["size"]
                while chunk := response.read(min(1024 * 1024, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError("Download exceeds locked size")
                    output.write(chunk)
            if not verified_file(temporary, metadata):
                temporary.unlink(missing_ok=True)
                raise ValueError("Downloaded model artifact failed integrity check")
            os.chmod(temporary, 0o644)
            temporary.replace(destination)
        print(f"Verified {operation}: {model['id']} @ {model['revision']}", flush=True)
    temporary = root / "manifest.json.partial"
    temporary.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(root / "manifest.json")
    verify_bundle(root)
    print("All artifacts verified; offline runtime bundle ready.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", default=os.environ.get("MODEL_ROOT", "/models"))
    args = parser.parse_args()
    try:
        provision(Path(args.model_root))
    except Exception:
        print("Model provisioning failed; no ready bundle was produced.", file=sys.stderr)
        sys.exit(1)
