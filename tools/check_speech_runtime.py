"""Synthesize each installed voice to a temporary WAV, without playing audio."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from sls_audio import inspect_wav
from sls_speech import VOICES

SAMPLES = {
    "fr_FR": "Ceci est une annonce de test. Veuillez lire les instructions.",
    "de_DE": "Dies ist eine Testansage. Bitte lesen Sie die Anweisungen.",
    "pt_BR": "Este é um anúncio de teste. Leia as instruções.",
    "es_ES": "Este es un anuncio de prueba. Lea las instrucciones.",
}


def check(application=None):
    command = [str(application)] if application else [sys.executable, str(ROOT / "src" / "sls_mass_notify.py")]
    with tempfile.TemporaryDirectory(prefix="sls-speech-check-") as directory:
        request, output = Path(directory) / "request.json", Path(directory) / "speech.wav"
        for voice in VOICES:
            request.write_text(json.dumps({"voice": voice, "text": SAMPLES.get(
                voice[:5], "This is a test announcement. Please read the instructions.")}), encoding="utf-8")
            subprocess.run(command + ["--synthesize-announcement", str(request), str(output)],
                           timeout=60, check=True, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            result = inspect_wav(output)
            if result.seconds < 0.2 or result.channels != 1 or result.bits_per_sample != 16:
                raise ValueError(f"Invalid synthesized audio for {voice}")
            print(f"Verified offline speech: {voice}, {result.seconds:.2f}s PCM; no playback", flush=True)
            output.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path)
    args = parser.parse_args()
    check(args.application)
