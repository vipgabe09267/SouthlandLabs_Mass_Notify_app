"""Offline announcement speech and interruptible notification audio.

Piper runs in a hidden child process. Notification text stays on this computer;
neither the UI thread nor a PBX connection waits for speech synthesis.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import time
import wave

from sls_audio import inspect_wav
from sls_presentation import explicit_test_mode, field
from sls_voices import DEFAULT_VOICE, VOICES, VoiceStore, safe_voice, playback_voice

MAX_TEXT = 2000
MAX_SPEECH_SECONDS = 120
SYNTHESIS_TIMEOUT = 60
def announcement_text(alert) -> str:
    if str(field(alert, "kind")).lower() != "announcement":
        return ""
    # Use the normalized text, never image URLs, XML, HTML or raw payloads.
    body = str(field(alert, "body") or field(alert, "description") or "").strip()
    if not body:
        return ""
    title = str(field(alert, "title") or "Announcement").strip()
    value = f"{title}. {body}" if title.casefold() != body.casefold() else body
    # Piper's phoneme markup must not be interpreted from an untrusted message.
    value = " ".join(value.replace("[", " ").replace("]", " ").split())
    value = "".join(c for c in value if c.isprintable())
    if len(value) > MAX_TEXT:
        value = value[:MAX_TEXT].rsplit(" ", 1)[0] + ". Read the full announcement on screen."
    return ("Test announcement. " if explicit_test_mode(alert) is True else "") + value


def model_path(voice=DEFAULT_VOICE) -> Path:
    return VoiceStore().model(safe_voice(voice))


def synthesize_file(request_path: Path, output_path: Path) -> None:
    """Child-only entry point: bounded synthesis with no UI or playback."""
    if request_path.stat().st_size > 16 * 1024:
        raise ValueError("Speech request is too large")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if (not isinstance(request, dict) or not isinstance(request.get("voice"), str)
            or request["voice"] not in VOICES):
        raise ValueError("Invalid speech voice")
    text = request.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT + 150:
        raise ValueError("Invalid speech request")
    from piper import PiperVoice
    from piper.config import PiperConfig
    import onnxruntime
    model = model_path(request["voice"])
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    voice = PiperVoice(config=PiperConfig.from_dict(json.loads(
        model.with_suffix(".onnx.json").read_text(encoding="utf-8"))),
        session=onnxruntime.InferenceSession(str(model), sess_options=options,
                                          providers=["CPUExecutionProvider"]))
    voice.use_tashkeel = False  # No optional language-resource downloads.
    frames = 0
    with wave.open(str(output_path), "wb") as output:
        for chunk in voice.synthesize(text):
            if frames == 0:
                output.setnchannels(chunk.sample_channels)
                output.setsampwidth(chunk.sample_width)
                output.setframerate(chunk.sample_rate)
            available = MAX_SPEECH_SECONDS * chunk.sample_rate - frames
            if available <= 0:
                break
            data = chunk.audio_int16_bytes[:available * chunk.sample_width * chunk.sample_channels]
            output.writeframesraw(data)
            frames += len(data) // (chunk.sample_width * chunk.sample_channels)
    inspect_wav(output_path)


def synthesize_hidden(text: str, output: Path, cancelled: threading.Event, voice=DEFAULT_VOICE) -> bool:
    request = output.with_suffix(".json")
    request.write_text(json.dumps({"text": text, "voice": safe_voice(voice)}, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).with_name("sls_mass_notify.py")))
    command.extend(["--synthesize-announcement", str(request), str(output)])
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + SYNTHESIS_TIMEOUT
    try:
        while process.poll() is None:
            if cancelled.wait(0.05):
                return False
            if time.monotonic() >= deadline:
                raise TimeoutError("Piper synthesis timed out")
        if cancelled.is_set():
            return False
        if process.returncode:
            raise RuntimeError("Piper synthesis failed")
        inspect_wav(output)
        return True
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        request.unlink(missing_ok=True)


@dataclass
class AudioJob:
    record_id: str
    alert: object
    priority: int
    expires: float | None
    cancelled: threading.Event
    voice: str | None = None
    speech_enabled: bool | None = None
    tone_enabled: bool = True
    queued_at: float = 0.0


class NotificationAudio:
    """Serialize tones and speech; higher priority alerts interrupt immediately."""
    def __init__(self, *, tone, stop, on_error, on_success=None, on_activity=None, enabled=True, voice=DEFAULT_VOICE,
                 synthesize=synthesize_hidden, play=None, resolve_voice=playback_voice):
        self._tone, self._stop, self._on_error = tone, stop, on_error
        self._on_success = on_success
        self._on_activity = on_activity
        self._synthesize, self._play = synthesize, play
        self._resolve_voice = resolve_voice
        self._enabled = bool(enabled)
        self._voice = safe_voice(voice)
        self._condition = threading.Condition()
        self._pending: list[AudioJob] = []
        self._active: AudioJob | None = None
        self._completed: deque[str] = deque(maxlen=128)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="NotificationAudio", daemon=True)
        self._thread.start()

    def _halt(self):
        try:
            self._stop()
        except Exception:
            pass  # A failing output device must not prevent cancellation.

    def submit(self, record_id, alert, priority, expires=None, *, voice=None, speech_enabled=None, tone_enabled=True):
        with self._condition:
            if self._closed or record_id in self._completed:
                return
            if any(j.record_id == record_id for j in self._pending) or (
                    self._active and self._active.record_id == record_id
                    and not self._active.cancelled.is_set()):
                return
            if len(self._pending) >= 32:
                return
            if self._active and priority < self._active.priority:
                self._active.cancelled.set()
                self._halt()
            job = AudioJob(record_id, alert, priority, expires, threading.Event(),
                           safe_voice(voice) if voice is not None else None,
                           speech_enabled, tone_enabled, time.monotonic())
            self._pending.append(job)
            self._pending.sort(key=lambda j: j.priority)  # Stable FIFO per priority.
            self._condition.notify()

    def cancel(self, record_id=None):
        with self._condition:
            self._pending[:] = [j for j in self._pending if record_id is not None and j.record_id != record_id]
            if self._active and (record_id is None or self._active.record_id == record_id):
                self._active.cancelled.set()
                self._halt()

    def configure(self, enabled, voice=DEFAULT_VOICE):
        with self._condition:
            self._enabled = bool(enabled)
            self._voice = safe_voice(voice)
            if not enabled and self._active:
                self._active.cancelled.set()
                self._halt()

    def close(self):
        with self._condition:
            self._closed = True
            self.cancel()
            self._condition.notify()

    @staticmethod
    def _valid(job):
        if job.expires is not None and job.expires <= time.time():
            job.cancelled.set()
        return not job.cancelled.is_set()

    def _wait(self, job, seconds):
        deadline = time.monotonic() + max(0, min(float(seconds), MAX_SPEECH_SECONDS))
        while self._valid(job) and time.monotonic() < deadline:
            job.cancelled.wait(min(0.05, max(0, deadline - time.monotonic())))
        return self._valid(job)

    def _play_file(self, job, path):
        duration = inspect_wav(path).seconds
        with self._condition:
            if not self._valid(job) or not self._speech_enabled(job):
                return
            if self._play is not None:
                self._play(path)
            else:
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        self._wait(job, duration)
        with self._condition:
            self._halt()

    def _speech_enabled(self, job):
        return self._enabled if job.speech_enabled is None else job.speech_enabled

    def _activity(self, job, stage):
        if self._on_activity:
            try:
                self._on_activity(stage, job.voice or self._voice, time.monotonic() - job.queued_at)
            except Exception:
                pass  # Diagnostics must never interrupt notification playback.

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if self._closed:
                    return
                job = self._pending.pop(0)
                self._active = job
            failed = False
            preparing = False
            tone_finished = time.monotonic()
            try:
                with self._condition:
                    duration = self._tone(job.alert) if self._valid(job) and job.tone_enabled else 0
                tone_finished = time.monotonic() + max(0, min(float(duration), MAX_SPEECH_SECONDS))
                text = announcement_text(job.alert)
                with self._condition:
                    speak = self._speech_enabled(job) and bool(text) and self._valid(job)
                    voice = self._resolve_voice(job.voice or self._voice)
                    job.voice = voice
                if speak:
                    preparing = True
                    self._activity(job, "preparing")
                    with tempfile.TemporaryDirectory(prefix="sls-speech-") as directory:
                        output = Path(directory) / "speech.wav"
                        # The tone is asynchronous: synthesize while it plays,
                        # then wait only for any remaining tone, not both delays.
                        if (self._synthesize(text, output, job.cancelled, voice)
                                and self._wait(job, max(0, tone_finished - time.monotonic()))):
                            self._activity(job, "playing")
                            self._play_file(job, output)
                            if self._valid(job) and self._on_success:
                                self._on_success()
                else:
                    self._wait(job, max(0, tone_finished - time.monotonic()))
            except Exception as exc:
                failed = True
                # Never log message text or pass it to an external service.
                self._activity(job, "failed:" + type(exc).__name__)
                self._on_error("Announcement audio could not play. Read the notification on screen.")
                self._wait(job, max(0, tone_finished - time.monotonic()))
            finally:
                with self._condition:
                    self._halt()
                    if self._valid(job):
                        self._completed.append(job.record_id)
                        if preparing and not failed:
                            self._activity(job, "finished")
                    elif preparing:
                        self._activity(job, "cancelled")
                    self._active = None
