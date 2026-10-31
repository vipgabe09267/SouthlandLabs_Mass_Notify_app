"""Download one pinned optional voice and synthesize it through the packaged app."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from sll_audio import inspect_wav
from sll_voices import VoiceStore, read_catalog


def check(application):
    voice = "en_US-amy-low"
    bundled = application.parent / "_internal" / "tts"
    with tempfile.TemporaryDirectory(prefix="sll-optional-voice-", dir=ROOT / "build") as temporary:
        base = Path(temporary)
        from sll_legacy import APP_SHORT_NAME, COMPANY_NAME
        cache = base / COMPANY_NAME / APP_SHORT_NAME / "voices"
        store = VoiceStore(bundled=bundled, cache=cache, catalog=read_catalog(bundled / "voices.json"))
        assert store.location(voice) is None, "Optional voice was unexpectedly bundled"
        print("Checking explicit optional Amy download from the pinned HTTPS source...", flush=True)
        assert store.download(voice, threading.Event())
        assert store.model(voice).parent == cache / voice
        request, output = base / "request.json", base / "speech.wav"
        request.write_text(json.dumps({"voice": voice, "text": "This downloaded voice is ready for announcements."}), encoding="utf-8")
        environment = dict(os.environ, LOCALAPPDATA=str(base))
        subprocess.run([str(application), "--synthesize-announcement", str(request), str(output)],
                       env=environment, timeout=60, check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        result = inspect_wav(output)
        assert result.seconds > 0.2 and result.bits_per_sample == 16
        assert {p.name for p in bundled.glob("*.onnx")} == {"en_US-lessac-low.onnx"}
        print(f"Verified downloaded Amy in an isolated per-user cache: {result.seconds:.2f}s PCM; no UI or playback.", flush=True)


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve())
