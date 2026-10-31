"""Driver-completion regressions; no real device is opened and no sound plays."""
import ctypes
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import wave

import sll_playback as playback
from sll_audio import WavInfo


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def wait(self, _event, seconds):
        self.value += seconds


class Device:
    def __init__(self, clock, *, finished_at=.3, fail_at=None):
        self.clock = clock
        self.finished_at = finished_at
        self.fail_at = fail_at
        self.calls = []

    def step(self, name):
        self.calls.append(name)
        if name == self.fail_at:
            raise playback.PlaybackError('Synthetic device failure')

    def open(self): self.step('open')
    def prepare(self): self.step('prepare')
    def write(self): self.step('write')
    def done(self): return self.clock() >= self.finished_at
    def close(self, *, reset):
        self.calls.append(('close', reset, self.clock()))


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'speech.wav'
        with wave.open(str(self.path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b'\0\0' * 800)  # 50ms PCM, device may drain later.
        self.clock = Clock()
        self.device = Device(self.clock)
        self.factory = mock.Mock(return_value=self.device)
        self.player = playback.SpeechPlayback(backend_factory=self.factory,
                                              clock=self.clock, wait=self.clock.wait)

    def test_delayed_device_completion_outlives_nominal_wav_duration(self):
        self.assertTrue(self.player.play(self.path))
        self.assertGreaterEqual(self.clock(), .3)
        self.assertEqual(self.device.calls[:3], ['open', 'prepare', 'write'])
        self.assertEqual(self.device.calls[-1][1], False)
        pcm, info = self.factory.call_args.args
        self.assertEqual(len(pcm), 1600)
        self.assertEqual(info.seconds, .05)

    def test_stop_resets_owned_output_without_waiting_for_nominal_end(self):
        def wait(event, seconds):
            self.clock.wait(event, seconds)
            self.player.stop()
        self.player._wait = wait
        self.assertFalse(self.player.play(self.path))
        self.assertEqual(self.device.calls[-1][1], True)
        self.assertLess(self.clock(), self.device.finished_at)

    def test_expiry_callback_cancels_pending_device_output(self):
        self.assertFalse(self.player.play(self.path, lambda: self.clock() < .1))
        self.assertEqual(self.device.calls[-1][1], True)
        self.assertGreaterEqual(self.clock(), .1)

    def test_cancelled_before_start_never_opens_a_device(self):
        self.assertFalse(self.player.play(self.path, lambda: False))
        self.factory.assert_not_called()

    def test_stop_during_open_does_not_queue_samples(self):
        self.device.open = lambda: self.player.stop()
        self.assertFalse(self.player.play(self.path))
        self.assertNotIn('write', self.device.calls)
        self.assertTrue(self.device.calls[-1][1])

    def test_incomplete_driver_times_out_then_resets(self):
        self.device.finished_at = float('inf')
        with self.assertRaisesRegex(playback.PlaybackError, 'did not finish'):
            self.player.play(self.path)
        self.assertLessEqual(self.clock(), .05 + playback.DRAIN_MARGIN_SECONDS)
        self.assertTrue(self.device.calls[-1][1])

    def test_open_prepare_and_queue_failures_cleanup_and_allow_later_play(self):
        for phase in ('open', 'prepare', 'write'):
            with self.subTest(phase=phase):
                self.device.fail_at = phase
                with self.assertRaises(playback.PlaybackError):
                    self.player.play(self.path)
                self.assertTrue(self.device.calls[-1][1])
                self.device.fail_at = None
                self.assertTrue(self.player.play(self.path))

    def test_duplicate_play_rejected_while_output_is_active(self):
        attempts = []
        def wait(event, seconds):
            if not attempts:
                with self.assertRaisesRegex(playback.PlaybackError, 'already active'):
                    self.player.play(self.path)
                attempts.append(True)
            self.clock.wait(event, seconds)
        self.player._wait = wait
        self.assertTrue(self.player.play(self.path))
        self.assertEqual(attempts, [True])

    def test_cleanup_failure_blocks_reuse_after_driver_keeps_buffer(self):
        self.device.close = mock.Mock(side_effect=playback.PlaybackError('release failed'))
        with self.assertRaisesRegex(playback.PlaybackError, 'release failed'):
            self.player.play(self.path)
        with self.assertRaisesRegex(playback.PlaybackError, 'restart'):
            self.player.play(self.path)
        self.assertEqual(self.factory.call_count, 1)

    def test_invalid_wav_never_opens_a_device(self):
        self.path.write_bytes(b'not wave audio')
        with self.assertRaises(ValueError):
            self.player.play(self.path)
        self.factory.assert_not_called()

    def test_non_pcm_or_non_16_bit_speech_rejected(self):
        with wave.open(str(self.path), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(1); output.setframerate(8000)
            output.writeframes(b'\x80' * 80)
        with self.assertRaisesRegex(playback.PlaybackError, '16-bit PCM'):
            self.player.play(self.path)
        self.factory.assert_not_called()

    def test_cancellation_callback_failure_cleans_up_output(self):
        def active():
            if self.clock() >= .05:
                raise ValueError('callback failed')
            return True
        with self.assertRaisesRegex(ValueError, 'callback failed'):
            self.player.play(self.path, active)
        self.assertTrue(self.device.calls[-1][1])


class Function:
    def __init__(self, callback): self.callback = callback
    def __call__(self, *args): return self.callback(*args)


class NativeApi:
    def __init__(self):
        self.calls = []
        self.header = None
        self.unprepare_result = 0
        self.waveOutOpen = Function(self.open)
        self.waveOutPrepareHeader = Function(self.prepare)
        self.waveOutWrite = Function(self.write)
        self.waveOutReset = Function(self.reset)
        self.waveOutUnprepareHeader = Function(self.unprepare)
        self.waveOutClose = Function(self.close)

    def open(self, handle, mapper, fmt, callback, instance, flags):
        self.calls.append('open')
        ctypes.cast(handle, ctypes.POINTER(ctypes.c_void_p)).contents.value = 123
        self.format = ctypes.cast(fmt, ctypes.POINTER(playback.WaveFormat)).contents
        return 0

    def prepare(self, handle, header, size):
        self.calls.append('prepare')
        self.header = ctypes.cast(header, ctypes.POINTER(playback.WaveHeader)).contents
        self.size = size
        return 0

    def write(self, *_): self.calls.append('write'); return 0
    def reset(self, *_): self.calls.append('reset'); self.header.flags |= playback.WHDR_DONE; return 0
    def unprepare(self, *_): self.calls.append('unprepare'); return self.unprepare_result
    def close(self, *_): self.calls.append('close'); return 0


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api = NativeApi()
        self.pcm = b'\x01\x02' * 800
        self.info = WavInfo(.05, 1, 16000, 16, 1, len(self.pcm))
        self.device = playback._WaveOutDevice(self.pcm, self.info, api=self.api)

    def test_x64_structures_and_pcm_lengths_match_windows_abi(self):
        self.assertEqual(ctypes.sizeof(playback.WaveFormat), 18)
        self.assertEqual(ctypes.sizeof(playback.WaveHeader), 48 if ctypes.sizeof(ctypes.c_void_p) == 8 else 32)
        self.device.open(); self.device.prepare(); self.device.write()
        self.assertEqual(self.api.format.sample_rate, 16000)
        self.assertEqual(self.api.format.byte_rate, 32000)
        self.assertEqual(self.api.header.length, len(self.pcm))
        self.assertEqual(ctypes.string_at(self.api.header.data, self.api.header.length), self.pcm)
        self.assertFalse(self.device.done())
        self.api.header.flags |= playback.WHDR_DONE
        self.assertTrue(self.device.done())
        self.device.close(reset=False)
        self.assertEqual(self.api.calls, ['open', 'prepare', 'write', 'unprepare', 'close'])

    def test_cancel_resets_before_unprepare_and_close(self):
        self.device.open(); self.device.prepare(); self.device.write()
        self.device.close(reset=True)
        self.assertEqual(self.api.calls[-3:], ['reset', 'unprepare', 'close'])
        self.assertFalse(self.device.opened)
        self.assertFalse(self.device.prepared)

    def test_unreleased_driver_buffer_is_retained_in_bounded_quarantine(self):
        self.device.open(); self.device.prepare(); self.device.write()
        self.api.unprepare_result = playback.WAVERR_STILLPLAYING
        with mock.patch.object(playback, 'CLEANUP_SECONDS', 0), mock.patch.object(playback, '_QUARANTINED_DEVICES', []):
            with self.assertRaisesRegex(playback.PlaybackError, 'release audio'):
                self.device.close(reset=True)
            self.assertIn(self.device, playback._QUARANTINED_DEVICES)
            self.assertTrue(self.device.prepared)
            self.assertEqual(ctypes.string_at(self.device.header.data, self.device.header.length), self.pcm)
            self.assertNotIn('close', self.api.calls)


if __name__ == '__main__':
    unittest.main()
