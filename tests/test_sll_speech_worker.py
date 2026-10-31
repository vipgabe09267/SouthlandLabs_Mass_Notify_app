"""Reusable speech helper failure paths; no native voice, UI or playback."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import sll_speech as speech
import sll_speech_worker as worker
from sll_voices import DEFAULT_VOICE
from tests.test_sll_speech import wav


class FakeProcess:
    def __init__(self, base, *, delay=0, stall=False, wrong_id=False, fail=False):
        self.base, self.stall = base, stall
        self.returncode = None
        self.pid = 10000
        self.requests = []
        self.done = threading.Event()
        self.received = threading.Event()
        self.thread = threading.Thread(target=self.run, args=(delay, wrong_id, fail), daemon=True)
        self.thread.start()

    def run(self, delay, wrong_id, fail):
        if self.done.wait(delay):
            return
        startup = worker.read_message(self.base / "startup.json")
        worker.write_message(self.base / "ready.json", {"ok": True, "voice": startup["voice"]})
        while not self.done.wait(0.005):
            request_path = self.base / "request.json"
            if not request_path.exists():
                continue
            request = worker.read_message(request_path)
            self.requests.append(request)
            self.received.set()
            if self.stall:
                self.done.wait()
                return
            if fail:
                self.returncode = 1
                self.done.set()
                return
            wav(self.base / "speech.wav")
            request_path.unlink()
            worker.write_message(self.base / "result.json", {
                "ok": True, "id": "different-request" if wrong_id else request["id"]})

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self.done.set()

    def wait(self, timeout):
        if not self.done.wait(timeout):
            raise TimeoutError("Fixture did not stop")
        self.thread.join(timeout)
        return self.returncode


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.processes = []
        self.options = {}
        self.launched = threading.Event()
        self.worker = worker.PiperWorker()
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch("sll_voices.playback_voice", side_effect=lambda value: value))
        self.launch = self.enterContext(mock.patch.object(worker.subprocess, "Popen", side_effect=self.start))
        self.addCleanup(self.cleanup)

    def start(self, command, **kwargs):
        self.assertEqual(kwargs["creationflags"], worker.subprocess.CREATE_NO_WINDOW)
        base = Path(command[command.index("--speech-worker") + 1])
        process = FakeProcess(base, **self.options)
        self.processes.append(process)
        self.launched.set()
        return process

    def cleanup(self):
        self.worker.close()
        self.assertTrue(self.worker.stopped.wait(2))
        self.assertTrue(all(process.poll() is not None for process in self.processes))

    def synthesize(self, name, cancelled=None, voice=DEFAULT_VOICE):
        return self.worker.synthesize("Private synthetic notification", Path(self.directory) / name,
                                      cancelled or threading.Event(), voice)

    def test_warmed_worker_reuses_model_process_for_consecutive_notifications(self):
        self.worker.prewarm(DEFAULT_VOICE)
        self.assertTrue(self.worker.ready.wait(2))
        self.assertTrue(self.synthesize("first.wav"))
        self.assertTrue(self.synthesize("second.wav"))
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(len(self.processes[0].requests), 2)
        base = self.processes[0].base
        self.assertFalse((base / "request.json").exists())
        self.assertFalse((base / "result.json").exists())
        self.assertFalse((base / "speech.wav").exists())
        self.assertNotIn("Private synthetic", str(self.launch.call_args))

    def test_cancelled_synthesis_stops_helper_and_next_notification_recovers(self):
        self.options["stall"] = True
        cancelled = threading.Event()
        result = []
        thread = threading.Thread(target=lambda: result.append(self.synthesize("cancelled.wav", cancelled)))
        thread.start()
        self.assertTrue(self.launched.wait(2))
        self.assertTrue(self.processes[0].received.wait(2))
        cancelled.set()
        thread.join(2)
        self.assertEqual(result, [False])
        self.assertFalse(self.processes[0].base.exists())
        self.assertFalse((Path(self.directory) / "cancelled.wav").exists())
        self.options.clear()
        self.assertTrue(self.synthesize("next.wav"))
        self.assertEqual(len(self.processes), 2)

    def test_deadline_covers_hung_native_synthesis_and_removes_private_files(self):
        self.options["stall"] = True
        with mock.patch.object(speech, "SYNTHESIS_TIMEOUT", 0.15):
            with self.assertRaises(TimeoutError):
                self.synthesize("timeout.wav")
        self.assertFalse(self.processes[0].base.exists())
        self.assertFalse((Path(self.directory) / "timeout.wav").exists())

    def test_other_request_result_is_never_published(self):
        self.options["wrong_id"] = True
        with mock.patch.object(speech, "SYNTHESIS_TIMEOUT", 0.15):
            with self.assertRaises(TimeoutError):
                self.synthesize("wrong.wav")
        self.assertFalse((Path(self.directory) / "wrong.wav").exists())

    def test_worker_exit_does_not_break_following_notification(self):
        self.options["fail"] = True
        with self.assertRaises(RuntimeError):
            self.synthesize("failed.wav")
        self.options.clear()
        self.assertTrue(self.synthesize("recovered.wav"))
        self.assertEqual(len(self.processes), 2)

    def test_voice_change_stops_previous_model_before_loading_another(self):
        self.assertTrue(self.synthesize("lessac.wav"))
        self.assertTrue(self.synthesize("amy.wav", voice="en_US-amy-low"))
        self.assertEqual(len(self.processes), 2)
        self.assertEqual(self.processes[0].returncode, -9)
        self.assertEqual(worker.read_message(self.processes[1].base / "startup.json")["voice"], "en_US-amy-low")

    def test_warmup_coalesces_voice_changes_and_keeps_only_the_last_selection(self):
        self.options["delay"] = 0.15
        self.worker.prewarm(DEFAULT_VOICE)
        self.assertTrue(self.launched.wait(2))
        for voice in ["en_US-amy-low", DEFAULT_VOICE] * 5 + ["en_US-amy-low"]:
            self.worker.prewarm(voice)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.worker._state:
                if not self.worker._warming:
                    break
            time.sleep(0.005)
        self.assertTrue(self.worker.ready.is_set())
        self.assertEqual(self.worker._voice, "en_US-amy-low")
        self.assertEqual(len(self.processes), 2)

    def test_missing_selected_voice_warms_the_bundled_fallback(self):
        with mock.patch("sll_voices.playback_voice", return_value=DEFAULT_VOICE):
            self.worker.prewarm("en_US-amy-low")
            self.assertTrue(self.worker.ready.wait(2))
        self.assertEqual(self.worker._voice, DEFAULT_VOICE)

    def test_closing_during_warmup_returns_promptly_and_reaps_helper(self):
        self.options["delay"] = 10
        self.worker.prewarm(DEFAULT_VOICE)
        self.assertTrue(self.launched.wait(2))
        started = time.monotonic()
        self.worker.close()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(self.worker.stopped.wait(2))
        self.assertFalse(self.processes[0].base.exists())

    def test_cancelled_job_does_not_start_or_stop_a_cached_helper(self):
        self.assertTrue(self.synthesize("first.wav"))
        cancelled = threading.Event()
        cancelled.set()
        self.assertFalse(self.synthesize("cancelled.wav", cancelled))
        self.assertEqual(len(self.processes), 1)
        self.assertIsNone(self.processes[0].returncode)

    def test_message_reader_bounds_data_before_decoding(self):
        path = Path(self.directory) / "oversize.json"
        path.write_bytes(b"x" * (16 * 1024 + 1))
        with self.assertRaises(ValueError):
            worker.read_message(path)
