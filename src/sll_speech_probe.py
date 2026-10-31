"""Silent preview and received-notification checks with the real Piper worker."""
from array import array
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import wave


def check(client):
    import sll_presentation as presentation
    import sll_speech as speech
    from sll_speech import NotificationAudio
    from sll_audio import inspect_wav
    from sll_store import Inbox

    class Root:
        def after(self, *_args): return None
        def after_idle(self, *_args): return None
        def after_cancel(self, *_args): pass

    class View:
        def __init__(self, _presenter, item, _offset):
            self.item = item
            self.shown_at = time.monotonic()
        def close(self): pass

    played, errors, stages, synthesis_times, worker_pids = [], [], [], [], []
    completions, premature_stops = [], []
    tail_marker = b"\x7b\x1e" * 16
    original_play, original_view, original_log = client.winsound.PlaySound, presentation._AlertView, client.log
    original_native_playback = speech.SpeechPlayback

    def intercept(path, flags):
        if path and Path(path).name == "speech.wav":
            raise RuntimeError("Speech bypassed its completion-aware playback adapter")

    def forbid_native_playback(*_args, **_kwargs):
        raise RuntimeError("A silent speech probe must not construct a native audio adapter")

    class CompletionPlayback:
        """Consume real PCM silently, with a device completion after its duration."""
        def __init__(self):
            self.active = None

        def play(self, path, should_continue):
            path = Path(path)
            info = inspect_wav(path)
            with wave.open(str(path), "rb") as source:
                frames = source.getnframes()
                pcm = source.readframes(frames)
            samples = array("h", pcm)
            if (not samples or max(abs(sample) for sample in samples) < 100
                    or len(pcm) != info.data_bytes or not pcm.endswith(tail_marker)):
                raise ValueError("Speech playback did not receive the complete marked PCM buffer")
            current = {"path": path, "stopped": threading.Event(), "done": False}
            self.active = current
            # Model output buffering/startup latency beyond the WAV's duration.
            # A duration-based caller must not halt or clean up this buffer early.
            started = time.monotonic()
            deadline = started + info.seconds + .075
            try:
                while time.monotonic() < deadline:
                    if not should_continue() or current["stopped"].wait(.005):
                        return False
                    if not path.is_file():
                        raise RuntimeError("Speech WAV was removed before device completion")
                if not should_continue():
                    return False
                current["done"] = True
                completions.append({"frames": frames, "bytes": len(pcm),
                    "tail_marker_consumed": True, "completion_after_duration":
                    time.monotonic() - started >= info.seconds + .05})
                played.append(round(info.seconds, 3))
                return True
            finally:
                self.active = None

        def stop(self):
            if self.active is not None and not self.active["done"]:
                premature_stops.append(True)
                self.active["stopped"].set()

    playback = CompletionPlayback()

    def activity(stage, voice, elapsed):
        if stage == "finished" and (playback.active is not None
                or len(completions) != sum(item[0] == "finished" for item in stages) + 1):
            errors.append("Speech was reported finished before device completion")
        stages.append((stage, round(elapsed, 3)))

    audio = presenter = app = None
    try:
        client.winsound.PlaySound = intercept
        speech.SpeechPlayback = forbid_native_playback
        presentation._AlertView = View
        client.log = lambda *_: None
        # Construct delivery state only: no Tk, IPC, tray, saved settings,
        # credentials, production inbox, monitor or network thread is opened.
        app = client.MassNotifyApp.__new__(client.MassNotifyApp)
        app.root = Root()
        profile = client.normalize_endpoint({"endpoint": "https://speech.example.invalid",
            "username": "speech-fixture", "password": "synthetic", "desktop_client_id": "speech-fixture"}, 0)
        app.config = client.normalize_config({"endpoints": [profile], "enabled": True})
        app.config_lock, app.worker_lock, app.faults_lock = threading.RLock(), threading.RLock(), threading.RLock()
        app.stop_event, app.wakeup_event = threading.Event(), threading.Event()
        app.ui_queue = client.ControlQueue()
        app.faults, app.transport_statuses, app.workers = {}, {}, {}
        app._scheduled_records = set()
        app._last_delivery_tick = time.time()
        app.inbox = Inbox(":memory:")
        audio = app.notification_audio = NotificationAudio(tone=app.play_notification_sound,
            stop=lambda: client.winsound.PlaySound(None, 0), on_error=errors.append,
            on_activity=activity, playback=playback)
        if not audio._worker.ready.wait(30):
            raise RuntimeError("Piper warmup did not complete")
        initial_pid = audio._worker._process.pid
        synthesize = audio._synthesize

        def measured(*arguments):
            started = time.monotonic()
            result = synthesize(*arguments)
            if result:
                output = Path(arguments[1])
                with wave.open(str(output), "rb") as source:
                    parameters, pcm = source.getparams(), source.readframes(source.getnframes())
                if parameters.nchannels != 1 or parameters.sampwidth != 2:
                    raise RuntimeError("The speech probe requires the included mono PCM voice")
                samples = array("h", pcm)
                if not samples or max(abs(sample) for sample in samples) < 100:
                    raise ValueError("Piper synthesized no usable audio before the probe marker")
                # A probe-only sentinel proves the final frame reaches the
                # playback adapter; the entire adapter is silent and injected.
                with wave.open(str(output), "wb") as destination:
                    destination.setparams(parameters)
                    destination.writeframes(pcm + tail_marker)
            synthesis_times.append(round(time.monotonic() - started, 3))
            worker_pids.append(audio._worker._process.pid)
            return result

        audio._synthesize = measured
        presenter = app.presenter = presentation.AlertPresenter(app.root, app.alert_displayed,
            app.alert_acknowledged, app.alert_failed, audio_handler=audio.submit,
            cancel_audio=audio.cancel, can_display=app.can_display_record)

        def wait_for_audio(count):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                app.check_delivery_resume()
                if errors or app.faults:
                    raise RuntimeError("Notification audio reported a failure")
                with audio._condition:
                    if len(played) == count and audio._active is None and not audio._pending:
                        return
                time.sleep(0.025)
            raise RuntimeError("Notification did not finish its intercepted speech playback")

        app.preview_notification()
        wait_for_audio(1)
        presenter._respond(next(iter(presenter.visible)), "dismissed")
        transport = client.EndpointTransportWorker(app, 0, app.config["endpoints"][0])
        app.workers[0] = transport
        received = [
            {"id": "received-announcement", "kind": "announcement", "title": "Announcement",
             "message": "Please read these instructions.", "priority": "notice", "is_test": False,
             "display_timeout_seconds": 0, "beep": "yes", "image_url": "https://speech.example.invalid/card.png"},
            {"id": "received-weather", "kind": "alert", "title": "Weather alert", "severity": "Severe",
             "description": "Severe weather is approaching.", "instructions": "Move indoors and stay away from windows.",
             "is_test": True, "beep": "no", "expires": (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()},
        ]
        for index, payload in enumerate(received, start=2):
            app.check_delivery_resume()
            payload.update(desktop_all=True, created_at=datetime.now(timezone.utc).isoformat())
            if not transport._accept_payload(payload, json.dumps(payload), payload["id"]):
                raise RuntimeError("Synthetic received notification was not durably accepted")
            app.pump_inbox()
            wait_for_audio(index)
            record = next(row for row in app.inbox.history() if row["event_id"] == payload["id"])
            presenter._respond(record["record_id"], "dismissed")
        if (len(completions) != 3 or premature_stops or errors
                or not all(item["tail_marker_consumed"] and item["completion_after_duration"] for item in completions)
                or sum(item[0] == "finished" for item in stages) != 3):
            raise RuntimeError("Speech did not retain and complete every PCM buffer through its final frame")
        if worker_pids != [initial_pid] * 3:
            raise RuntimeError("Notification speech restarted its warmed process")
        if len(app.inbox.history()) != 2 or len(app.inbox.pending_receipts(client.profile_namespace(profile))) != 2:
            raise RuntimeError("Received notification/receipt state did not survive speech playback")
        return {"voice_playback_calls": len(played), "speech_seconds": played, "stages": stages,
                "device_completions": len(completions), "complete_pcm_buffers": completions,
                "synthesis_seconds": synthesis_times, "reused_worker": True, "received_records": 2,
                "output": "Synthetic delivery and memory inbox; no PBX requests, windows or sound; full PCM and delayed device completion simulated"}
    finally:
        if presenter:
            presenter.shutdown()
        if audio:
            audio.close()
            audio._thread.join(5)
            if audio._worker and not audio._worker.stopped.wait(5):
                raise RuntimeError("Piper helper did not stop")
        if app and hasattr(app, "inbox"):
            app.inbox.close()
        client.winsound.PlaySound, presentation._AlertView, client.log = original_play, original_view, original_log
        speech.SpeechPlayback = original_native_playback
