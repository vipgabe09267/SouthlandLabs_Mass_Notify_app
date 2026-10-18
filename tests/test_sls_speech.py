import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import sls_speech as speech
import sls_mass_notify as client
from tests.test_sls_client_reliability import IsolatedClientTest


def announcement(body="Check the lobby.", **kwargs):
    return dict(kind="announcement", title="Announcement", body=body, **kwargs)


def wav(path):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16)


class TextTests(unittest.TestCase):
    def test_defaults_and_voice_allowlist(self):
        self.assertIs(client.default_config()["announcement_tts_enabled"], True)
        self.assertEqual(client.normalize_config({})["announcement_tts_voice"], "en_US-lessac-low")
        self.assertEqual(len(speech.VOICES), 8)
        for value in ("../../model", None, "en_US-lessac-low.onnx", {}, False):
            self.assertEqual(speech.safe_voice(value), speech.DEFAULT_VOICE)

    def test_read_normalized_announcements_only(self):
        self.assertEqual(speech.announcement_text(announcement()), "Announcement. Check the lobby.")
        self.assertEqual(speech.announcement_text(dict(kind="alert", body="Weather alert")), "")
        self.assertEqual(speech.announcement_text(announcement("", image_url="https://example.invalid/raw.xml")), "")
        self.assertNotIn("[[", speech.announcement_text(announcement("[[injected]]\0 message")))
        self.assertNotIn("\0", speech.announcement_text(announcement("\0 message")))

    def test_explicit_tests_are_announced_without_guessing_from_wording(self):
        self.assertTrue(speech.announcement_text(announcement(raw={"is_test": True})).startswith("Test announcement."))
        self.assertFalse(speech.announcement_text(announcement("test wording", raw={"is_test": False})).startswith("Test announcement."))

    def test_long_messages_are_bounded_and_direct_user_to_full_text(self):
        value = speech.announcement_text(announcement("long message " * 2000))
        self.assertLessEqual(len(value), speech.MAX_TEXT + 150)
        self.assertTrue(value.endswith("Read the full announcement on screen."))

    def test_child_refuses_unknown_voice_and_oversize_request_before_importing_piper(self):
        with tempfile.TemporaryDirectory() as directory:
            request, output = Path(directory) / "request.json", Path(directory) / "out.wav"
            for data in ({"voice": "../../untrusted", "text": "hello"},
                         {"voice": speech.DEFAULT_VOICE, "text": "x" * 2200}, []):
                request.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    speech.synthesize_file(request, output)
                self.assertFalse(output.exists())

    def test_hidden_child_cancellation_terminates_process_and_removes_request_text(self):
        process = Mock()
        process.poll.return_value = None
        cancelled = threading.Event()
        cancelled.set()
        with tempfile.TemporaryDirectory() as directory, patch.object(
                speech.subprocess, "Popen", return_value=process) as launch:
            output = Path(directory) / "speech.wav"
            self.assertFalse(speech.synthesize_hidden("private announcement", output, cancelled))
            process.kill.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            self.assertFalse(output.with_suffix(".json").exists())
            self.assertNotIn("private announcement", str(launch.call_args))
            self.assertEqual(launch.call_args.kwargs["creationflags"], speech.subprocess.CREATE_NO_WINDOW)

    def test_model_manifest_covers_exactly_the_requested_voices_with_pinned_assets(self):
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads((root / "tools" / "piper-voices.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 24)
        expected = {voice + suffix for voice in speech.VOICES for suffix in (".onnx", ".onnx.json", ".MODEL_CARD")}
        self.assertEqual({entry["name"] for entry in manifest["files"]}, expected)
        for entry in manifest["files"]:
            self.assertIn(manifest["revision"], entry["url"])
            self.assertRegex(entry["sha256"], r"^[a-f0-9]{64}$")


class SettingsTests(IsolatedClientTest):
    def test_voice_button_uses_unsaved_selection_without_changing_saved_preferences(self):
        original = self.instance.get_config()
        window = client.SettingsWindow.__new__(client.SettingsWindow)
        window.app = self.instance
        window.tts_voice_var = Mock(get=lambda: speech.VOICES["fr_FR-siwis-medium"])
        with patch.object(client, "voice_available", return_value=True):
            window.test_selected_voice()
        call = self.instance.notification_audio.submit.call_args
        self.assertEqual(call.kwargs["voice"], "fr_FR-siwis-medium")
        self.assertIs(call.kwargs["speech_enabled"], True)
        self.assertIs(call.kwargs["tone_enabled"], False)
        self.assertTrue(call.args[0].startswith("voice-test-"))
        self.assertEqual(self.instance.get_config(), original)
        self.assertFalse(client.CONFIG_PATH.exists())

    def test_speech_preferences_are_saved_and_applied_without_changing_authentication(self):
        self.instance.update_settings(endpoints=[self.profile], enabled=True,
            startup_enabled=True, auto_update_enabled=False, audio_sound=client.DEFAULT_AUDIO_NAME,
            announcement_tts_enabled=False, announcement_tts_voice="de_DE-thorsten-low")
        saved = json.loads(client.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIs(saved["announcement_tts_enabled"], False)
        self.assertEqual(saved["announcement_tts_voice"], "de_DE-thorsten-low")
        self.assertEqual(saved["endpoints"][0]["username"], self.profile["username"])
        self.instance.notification_audio.configure.assert_called_once_with(False, "de_DE-thorsten-low")

    def test_failed_save_does_not_apply_speech_preferences(self):
        with patch.object(client, "save_config", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.instance.update_settings(endpoints=[self.profile], enabled=True,
                    startup_enabled=True, auto_update_enabled=False, audio_sound=client.DEFAULT_AUDIO_NAME,
                    announcement_tts_enabled=False)
        self.assertIs(self.instance.get_config()["announcement_tts_enabled"], True)
        self.instance.notification_audio.configure.assert_not_called()


class QueueTests(unittest.TestCase):
    def test_synthesis_starts_while_tone_is_still_playing(self):
        started = threading.Event()
        def synth(text, path, cancelled, voice):
            started.set()
            wav(path)
            return True
        audio = self.make(tone=lambda alert: 30, synthesize=synth)
        audio.submit("one", announcement(), 3)
        self.assertTrue(started.wait(1), "Speech preparation must not wait for the entire tone")
        self.assertFalse(self.played, "Prepared speech must not interrupt the tone")
        audio.cancel("one")
        self.idle()

    def test_voice_test_uses_selected_voice_when_disabled_without_changing_preferences(self):
        audio = self.make(enabled=False, voice="en_US-lessac-low")
        audio.submit("preview", announcement(), 3, voice="es_ES-davefx-medium",
                     speech_enabled=True, tone_enabled=False)
        self.idle()
        self.assertFalse(self.tones)
        self.assertEqual(self.spoken[0][1], "es_ES-davefx-medium")
        self.assertFalse(audio._enabled)
        self.assertEqual(audio._voice, "en_US-lessac-low")
        audio.submit("normal", announcement(), 3)
        self.idle()
        self.assertEqual(len(self.spoken), 1)

    def setUp(self):
        self.spoken, self.tones, self.played, self.errors = [], [], [], []
        self.finished = threading.Event()
        self.stop = Mock()
        def synth(text, path, cancelled, voice):
            self.spoken.append((text, voice))
            wav(path)
            return not cancelled.is_set()
        self.synth = synth
        self.controller = None

    def make(self, **kwargs):
        kwargs.setdefault("resolve_voice", lambda voice: voice)
        self.controller = speech.NotificationAudio(
            tone=kwargs.pop("tone", lambda alert: self.tones.append(alert) or 0),
            stop=self.stop, on_error=self.errors.append,
            synthesize=kwargs.pop("synthesize", self.synth),
            play=lambda path: self.played.append(path), **kwargs)
        return self.controller

    def idle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.controller._condition:
                if not self.controller._pending and self.controller._active is None:
                    return
            time.sleep(0.005)
        self.fail("Audio worker did not finish")

    def tearDown(self):
        if self.controller:
            self.controller.close()
            self.controller._thread.join(3)
            self.assertFalse(self.controller._thread.is_alive())

    def test_two_announcements_are_serialized_and_duplicates_do_not_repeat(self):
        audio = self.make()
        audio.submit("one", announcement("first"), 3)
        audio.submit("two", announcement("second"), 3)
        audio.submit("one", announcement("duplicate"), 3)
        self.idle()
        audio.submit("one", announcement("duplicate later"), 3)
        self.idle()
        self.assertEqual([s[0] for s in self.spoken], ["Announcement. first", "Announcement. second"])
        self.assertEqual(len(self.played), 2)
        self.assertTrue(all(not path.exists() for path in self.played))
        self.assertFalse(self.errors)

    def test_disable_keeps_tones_and_selected_voice_is_used_when_reenabled(self):
        audio = self.make(enabled=False)
        audio.submit("one", announcement(), 3)
        self.idle()
        self.assertEqual(len(self.tones), 1)
        self.assertFalse(self.spoken)
        audio.configure(True, "fr_FR-siwis-medium")
        audio.submit("two", announcement("Bonjour"), 3)
        self.idle()
        self.assertEqual(self.spoken[0][1], "fr_FR-siwis-medium")

    def test_expired_jobs_neither_play_nor_synthesize(self):
        audio = self.make()
        audio.submit("old", announcement(), 3, time.time() - 1)
        self.idle()
        self.assertFalse(self.tones)
        self.assertFalse(self.spoken)

    def test_dismiss_cancels_active_synthesis_and_removes_waiting_job(self):
        started, release = threading.Event(), threading.Event()
        def synth(text, path, cancelled, voice):
            started.set()
            self.assertTrue(release.wait(2))
            wav(path)
            return True  # Even a late result must not be played.
        audio = self.make(synthesize=synth)
        audio.submit("one", announcement(), 3)
        self.assertTrue(started.wait(2))
        audio.submit("two", announcement(), 3)
        audio.cancel("two")
        audio.cancel("one")
        release.set()
        self.idle()
        self.assertFalse(self.played)
        self.assertEqual(len(self.tones), 1)
        self.stop.assert_called()

    def test_critical_weather_interrupts_speech_without_reading_weather_raw_text(self):
        started = threading.Event()
        def synth(text, path, cancelled, voice):
            started.set()
            self.assertTrue(cancelled.wait(2))
            return False
        audio = self.make(synthesize=synth)
        audio.submit("announcement", announcement(), 3)
        self.assertTrue(started.wait(2))
        audio.submit("critical", {"kind": "alert", "body": "Weather raw text"}, 0)
        self.idle()
        self.assertEqual(len(self.tones), 2)
        self.assertFalse(self.played)

    def test_synthesis_failure_keeps_worker_alive_for_next_notification(self):
        calls = []
        def synth(text, path, cancelled, voice):
            calls.append(text)
            if len(calls) == 1:
                raise RuntimeError("private text must never be logged")
            return self.synth(text, path, cancelled, voice)
        audio = self.make(synthesize=synth)
        audio.submit("one", announcement(), 3)
        audio.submit("two", announcement(), 3)
        self.idle()
        self.assertEqual(len(self.played), 1)
        self.assertEqual(len(self.errors), 1)
        self.assertNotIn("private", self.errors[0])

    def test_disabling_during_synthesis_blocks_late_playback(self):
        started, release = threading.Event(), threading.Event()
        def synth(text, path, cancelled, voice):
            started.set()
            self.assertTrue(release.wait(2))
            wav(path)
            return True
        audio = self.make(synthesize=synth)
        audio.submit("one", announcement(), 3)
        self.assertTrue(started.wait(2))
        audio.configure(False)
        release.set()
        self.idle()
        self.assertFalse(self.played)

    def test_cancelled_record_can_resume_before_its_old_synthesis_returns(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def synth(text, path, cancelled, voice):
            calls.append(text)
            if len(calls) == 1:
                started.set()
                self.assertTrue(release.wait(2))
                return False
            return self.synth(text, path, cancelled, voice)
        audio = self.make(synthesize=synth)
        audio.submit("routine", announcement(), 3)
        self.assertTrue(started.wait(2))
        audio.cancel()
        audio.submit("routine", announcement(), 3)
        release.set()
        self.idle()
        self.assertEqual(len(self.played), 1)


if __name__ == "__main__":
    unittest.main()
