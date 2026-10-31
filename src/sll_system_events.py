"""Windows lifecycle signals without Tk calls, polling, or device reporting."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import threading
import time


LOG = logging.getLogger(__name__)


class RecoverySignals:
    """Coalesce OS callbacks and fence delivery until the UI retires old sockets."""
    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = ""
        self._suspended = False
        self._last_network = float("-inf")
        self._last_resume = float("-inf")

    def signal(self, kind: str) -> None:
        if kind not in {"suspend", "resume", "network"}:
            raise ValueError("Unknown system event")
        now = time.monotonic()
        with self._lock:
            if kind == "network":
                if self._suspended or now - self._last_network < 2:
                    return
                self._last_network = now
                if self._pending in {"suspend", "resume"}:
                    return
            elif kind == "resume":
                # Windows can send AUTOMATIC and RESUMESUSPEND for one wake.
                if not self._suspended and now - self._last_resume < 2:
                    return
                self._last_resume = now
                self._suspended = False
            else:
                self._suspended = True
            self._generation += 1
            self._pending = kind

    @property
    def blocked(self) -> bool:
        with self._lock:
            return self._suspended or bool(self._pending)

    def snapshot(self) -> tuple[int, str, bool]:
        with self._lock:
            return self._generation, self._pending, self._suspended

    def complete(self, generation: int) -> None:
        with self._lock:
            if generation == self._generation:
                self._pending = ""


class AddressChangeSubscription:
    """Subscribe to address acquisition/loss; unregister outside the OS callback."""
    def __init__(self, callback):
        self.callback = callback
        self._handle = wintypes.HANDLE()
        self._api = None
        self._native_callback = None
        self._stopping = threading.Event()

    def _changed(self, _context, _row, notification_type):
        # MibAddInstance / MibDeleteInstance. Parameter updates and initial
        # registration don't prove connectivity changed and can be very noisy.
        if self._stopping.is_set() or notification_type not in (1, 2):
            return
        try:
            self.callback("network")
        except Exception:
            LOG.exception("Network change callback failed")

    def start(self) -> None:
        if os.name != "nt":
            raise OSError("Windows address notifications are unavailable")
        if self._handle.value:
            return
        self._stopping.clear()
        self._api = ctypes.WinDLL("iphlpapi", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
        self._native_callback = callback_type(self._changed)
        register = self._api.NotifyUnicastIpAddressChange
        register.argtypes = [ctypes.c_ushort, callback_type, ctypes.c_void_p,
                             ctypes.c_ubyte, ctypes.POINTER(wintypes.HANDLE)]
        register.restype = wintypes.ULONG
        self._api.CancelMibChangeNotify2.argtypes = [wintypes.HANDLE]
        self._api.CancelMibChangeNotify2.restype = wintypes.ULONG
        error = register(0, self._native_callback, None, False, ctypes.byref(self._handle))
        if error:
            self._native_callback = None
            raise ctypes.WinError(error)

    def close(self) -> None:
        # Called by the tray's message thread, never by _changed. Cancellation
        # waits for in-flight callbacks, so it must not hold their dependencies.
        self._stopping.set()
        if self._handle.value:
            error = self._api.CancelMibChangeNotify2(self._handle)
            if error:
                raise ctypes.WinError(error)
            self._handle = wintypes.HANDLE()
        self._native_callback = None
