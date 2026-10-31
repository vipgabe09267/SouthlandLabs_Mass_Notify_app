"""Owned Windows speech output that waits for the audio driver's completion.

Only this player's handle is reset on cancellation. Notification sounds and
Settings previews use their existing output path independently.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import struct
import threading
import time

from sll_audio import MAX_AUDIO_BYTES, WavInfo, inspect_wav_bytes


POLL_SECONDS = 0.05
DRAIN_MARGIN_SECONDS = 15.0
CLEANUP_SECONDS = 2.0
WHDR_DONE = 0x00000001
WAVERR_STILLPLAYING = 33
# A broken driver must never retain a pointer to memory Python then frees.
# At most one such device is retained; further native output fails closed.
_QUARANTINED_DEVICES = []
_DEVICE_STATE = threading.Lock()
_NATIVE_ACTIVE = False


class PlaybackError(RuntimeError):
    pass


class WaveFormat(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("format_tag", ctypes.c_uint16), ("channels", ctypes.c_uint16),
                ("sample_rate", ctypes.c_uint32), ("byte_rate", ctypes.c_uint32),
                ("block_align", ctypes.c_uint16), ("bits", ctypes.c_uint16),
                ("extra_size", ctypes.c_uint16)]


class WaveHeader(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("length", ctypes.c_uint32),
                ("recorded", ctypes.c_uint32), ("user", ctypes.c_size_t),
                ("flags", ctypes.c_uint32), ("loops", ctypes.c_uint32),
                ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


def _read_pcm(path):
    with Path(path).open("rb") as source:
        data = source.read(MAX_AUDIO_BYTES + 1)
    info = inspect_wav_bytes(data)
    if info.format_tag != 1 or info.bits_per_sample != 16:
        raise PlaybackError("Speech output requires 16-bit PCM audio.")
    offset = 12
    while offset < len(data):
        kind, size = struct.unpack_from("<4sI", data, offset)
        start = offset + 8
        if kind == b"data":
            return data[start:start + size], info
        offset = start + size + (size & 1)
    raise PlaybackError("Speech audio has no sample data.")


class _WaveOutDevice:
    def __init__(self, pcm: bytes, info: WavInfo, *, api=None):
        self.native = api is None
        self.claimed = False
        if api is None:
            if os.name != "nt":
                raise PlaybackError("Windows speech output is unavailable.")
            with _DEVICE_STATE:
                if _QUARANTINED_DEVICES:
                    raise PlaybackError("The speech device did not release prior audio; restart the app.")
            api = ctypes.WinDLL("winmm", use_last_error=True)
        self.api = api
        self.handle = ctypes.c_void_p()
        self.prepared = False
        self.opened = False
        self.buffer = ctypes.create_string_buffer(pcm)
        self.header = WaveHeader(data=ctypes.cast(self.buffer, ctypes.c_void_p), length=len(pcm))
        alignment = info.channels * 2
        self.format = WaveFormat(1, info.channels, info.sample_rate,
                                 info.sample_rate * alignment, alignment, 16, 0)
        signatures = (
            (api.waveOutOpen, [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32,
                              ctypes.POINTER(WaveFormat), ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint32]),
            (api.waveOutPrepareHeader, [ctypes.c_void_p, ctypes.POINTER(WaveHeader), ctypes.c_uint32]),
            (api.waveOutWrite, [ctypes.c_void_p, ctypes.POINTER(WaveHeader), ctypes.c_uint32]),
            (api.waveOutReset, [ctypes.c_void_p]),
            (api.waveOutUnprepareHeader, [ctypes.c_void_p, ctypes.POINTER(WaveHeader), ctypes.c_uint32]),
            (api.waveOutClose, [ctypes.c_void_p]),
        )
        for function, arguments in signatures:
            function.argtypes, function.restype = arguments, ctypes.c_uint32

    @staticmethod
    def _check(result, operation):
        if result:
            raise PlaybackError(f"Windows speech output could not {operation} (code {int(result)}).")

    def open(self):
        global _NATIVE_ACTIVE
        if self.native:
            with _DEVICE_STATE:
                if _NATIVE_ACTIVE or _QUARANTINED_DEVICES:
                    raise PlaybackError("Speech output already has an active or unreleased device.")
                _NATIVE_ACTIVE = self.claimed = True
        self._check(self.api.waveOutOpen(ctypes.byref(self.handle), 0xffffffff,
                                        ctypes.byref(self.format), 0, 0, 0), "open the device")
        self.opened = True

    def prepare(self):
        self._check(self.api.waveOutPrepareHeader(self.handle, ctypes.byref(self.header),
                                                 ctypes.sizeof(self.header)), "prepare audio")
        self.prepared = True

    def write(self):
        self._check(self.api.waveOutWrite(self.handle, ctypes.byref(self.header),
                                        ctypes.sizeof(self.header)), "queue audio")

    def done(self):
        return bool(self.header.flags & WHDR_DONE)

    def close(self, *, reset):
        """Keep sample memory alive until Windows returns its prepared buffer."""
        global _NATIVE_ACTIVE
        if not self.opened:
            if self.claimed:
                with _DEVICE_STATE:
                    _NATIVE_ACTIVE = self.claimed = False
            return
        try:
            if reset and self.prepared:
                # Still attempt unprepare/close if reset reports a device loss.
                # Those successful calls establish that no driver owns memory.
                self.api.waveOutReset(self.handle)
            if self.prepared:
                deadline = time.monotonic() + CLEANUP_SECONDS
                while True:
                    result = self.api.waveOutUnprepareHeader(self.handle, ctypes.byref(self.header),
                                                            ctypes.sizeof(self.header))
                    if result == 0:
                        self.prepared = False
                        break
                    if result != WAVERR_STILLPLAYING or time.monotonic() >= deadline:
                        self._check(result, "release audio")
                    # A driver can briefly return STILLPLAYING while processing
                    # reset. Retry only within the bounded cleanup interval.
                    if not reset:
                        self._check(self.api.waveOutReset(self.handle), "reset audio")
                        reset = True
                    time.sleep(0.01)
            self._check(self.api.waveOutClose(self.handle), "close the device")
            self.opened = False
            if self.claimed:
                with _DEVICE_STATE:
                    _NATIVE_ACTIVE = self.claimed = False
        except BaseException:
            if self.opened:
                with _DEVICE_STATE:
                    if not any(device is self for device in _QUARANTINED_DEVICES):
                        _QUARANTINED_DEVICES.append(self)
            raise


class SpeechPlayback:
    """One interruptible PCM playback at a time, completed by the driver."""
    def __init__(self, *, backend_factory=None, clock=time.monotonic, wait=None):
        self._factory = backend_factory or _WaveOutDevice
        self._clock = clock
        self._wait = wait or (lambda event, seconds: event.wait(seconds))
        self._lock = threading.Lock()
        self._session = None
        self._failed = False

    def stop(self):
        """Signal the playback worker; never call a driver from the UI thread."""
        with self._lock:
            session = self._session
        if session is not None:
            session.set()

    def play(self, path, should_continue=lambda: True):
        with self._lock:
            if self._session is not None:
                raise PlaybackError("Speech playback is already active.")
            if self._failed:
                raise PlaybackError("Speech output needs an app restart after a device cleanup failure.")
            session = self._session = threading.Event()
        device = None
        completed = False
        try:
            def active():
                return not session.is_set() and bool(should_continue())
            if not active():
                return False
            pcm, info = _read_pcm(path)
            if not active():
                return False
            device = self._factory(pcm, info)
            device.open()
            if not active():
                return False
            device.prepare()
            if not active():
                return False
            device.write()
            deadline = self._clock() + info.seconds + DRAIN_MARGIN_SECONDS
            while active():
                if device.done():
                    completed = True
                    return True
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise PlaybackError("The speech output device did not finish playback.")
                self._wait(session, min(POLL_SECONDS, remaining))
            return False
        finally:
            try:
                if device is not None:
                    device.close(reset=not completed)
            except BaseException:
                with self._lock:
                    self._failed = True
                raise
            finally:
                with self._lock:
                    if self._session is session:
                        self._session = None
