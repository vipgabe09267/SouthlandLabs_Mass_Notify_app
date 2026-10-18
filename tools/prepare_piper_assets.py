"""Cache pinned speech assets and stage only the included Lessac low voice."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from sls_voices import DEFAULT_VOICE, read_catalog
from sls_install_safety import remove_staging, reject_reparse


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
    manifest = read_catalog()
    for entry in manifest["files"]:
        if not entry["name"].startswith(DEFAULT_VOICE + "."):
            continue
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
    stage = ROOT / "build" / "tts"
    if not stage.resolve().is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Voice staging directory escaped build output")
    reject_reparse(stage)
    if stage.exists():
        remove_staging(stage)
    stage.mkdir(parents=True)
    for entry in manifest["files"]:
        if entry["name"].startswith(DEFAULT_VOICE + "."):
            shutil.copyfile(destination / entry["name"], stage / entry["name"])
    shutil.copyfile(ROOT / "tools/piper-voices.json", stage / "voices.json")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", stage / "THIRD_PARTY_NOTICES.md")
    print("Verified and staged Lessac low; seven optional voices remain download-only.")


if __name__ == "__main__":
    prepare()
