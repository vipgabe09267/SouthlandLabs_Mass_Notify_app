"""Silent end-to-end announcement audio check for the packaged application."""
from array import array
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import wave


def check(client):
    import sls_presentation as presentation
    from sls_speech import NotificationAudio
    from sls_audio import inspect_wav

    class Root:
        def after(self, *_args): return None
        def after_idle(self, *_args): return None
        def after_cancel(self, *_args): pass

    class View:
        def __init__(self, _presenter, item, _offset):
            self.item = item
            self.shown_at = time.monotonic()
        def close(self): pass

    done = threading.Event()
    played, errors, stages = [], [], []
    original_play, original_view = client.winsound.PlaySound, presentation._AlertView

    def intercept(path, flags):
        if not path or Path(path).name != "speech.wav":
            return
        info = inspect_wav(Path(path))
        with wave.open(str(path), "rb") as source:
            samples = array("h", source.readframes(min(source.getnframes(), source.getframerate() * 5)))
        if not samples or max(abs(sample) for sample in samples) < 100:
            raise ValueError("Synthesized speech has no usable audio signal")
        played.append(round(info.seconds, 3))
        if len(played) == 2:
            done.set()

    audio = presenter = None
    try:
        client.winsound.PlaySound = intercept
        presentation._AlertView = View
        app = SimpleNamespace(get_config=client.default_config, clear_fault=lambda *_: None,
                              record_fault=lambda *args: errors.append(args))
        audio = NotificationAudio(tone=lambda alert: client.MassNotifyApp.play_notification_sound(app, alert),
            stop=lambda: client.winsound.PlaySound(None, 0), on_error=errors.append,
            on_activity=lambda stage, voice, elapsed: stages.append((stage, round(elapsed, 3))))
        presenter = presentation.AlertPresenter(Root(), lambda *_: None, lambda *_: None, errors.append,
            audio_handler=audio.submit, cancel_audio=audio.cancel)
        app.present_alert = lambda alert: client.MassNotifyApp.present_alert(SimpleNamespace(presenter=presenter), alert)
        client.MassNotifyApp.preview_notification(app)
        alert = client.extract_alert({"kind": "announcement", "title": "Announcement",
            "body": "Please read these instructions.", "priority": "notice", "is_test": False}, "")
        presenter.submit("probe-announcement", alert)
        if not done.wait(45) or errors or len(played) != 2:
            raise RuntimeError("Announcement audio pipeline did not reach both playback calls")
        preparing = [elapsed for stage, elapsed in stages if stage == "preparing"]
        if not preparing or preparing[0] > 1.0:
            raise RuntimeError("Speech preparation waited for the notification tone")
        return {"voice_playback_calls": len(played), "speech_seconds": played, "stages": stages,
                "output": "Windows playback calls intercepted; no sound played; no windows created"}
    finally:
        if presenter:
            presenter.shutdown()
        if audio:
            audio.close()
            audio._thread.join(5)
        client.winsound.PlaySound = original_play
        presentation._AlertView = original_view
