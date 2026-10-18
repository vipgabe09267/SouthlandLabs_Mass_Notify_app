"""Download build-time voice assets from reviewed, size/hash-pinned URLs.

The installed app never downloads executable code or models at runtime.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def matches(path, entry):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != entry["size"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"]


def prepare():
    destination = ROOT / ".tools" / "tts"
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("Refusing linked speech asset directory")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "tools" / "piper-voices.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        name = entry["name"]
        if Path(name).name != name or not 0 < entry["size"] <= 80 * 1024 * 1024:
            raise ValueError("Invalid voice manifest entry")
        target = destination / name
        if matches(target, entry):
            continue
        print(f"Downloading pinned Piper asset: {name}", flush=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".voice-", dir=destination)
        temporary = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as output:
                with urllib.request.urlopen(entry["url"], timeout=60) as response:
                    total = 0
                    while block := response.read(1024 * 1024):
                        total += len(block)
                        if total > entry["size"]:
                            raise ValueError("Voice asset exceeded its pinned size")
                        output.write(block)
            if not matches(temporary, entry):
                raise ValueError(f"Voice asset integrity check failed: {name}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    print("Verified all eight Piper voices and model cards.")


if __name__ == "__main__":
    prepare()
