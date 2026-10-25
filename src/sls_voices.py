"""Pinned voice catalog, bundled default, and explicit per-user downloads."""
from pathlib import Path
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from functools import partial

from sls_install_safety import reject_reparse

DEFAULT_VOICE = "en_US-lessac-low"
VOICES = {
    "en_US-lessac-low": "English (US) · lessac · low (default)",
    "en_US-amy-low": "English (US) · amy · low",
    "en_US-lessac-medium": "English (US) · lessac · medium",
    "en_US-ryan-low": "English (US) · ryan · low",
    "fr_FR-siwis-medium": "French · siwis · medium",
    "de_DE-thorsten-low": "German · thorsten · low",
    "pt_BR-faber-medium": "Portuguese (Brazil) · faber · medium",
    "es_ES-davefx-medium": "Spanish · davefx · medium",
}
SUFFIXES = (".onnx", ".onnx.json", ".MODEL_CARD")
VOICE_DOWNLOAD_SECONDS = 600
VOICE_HEADER_SECONDS = 15


class VoiceDownloadCancelled(Exception):
    pass


def transfer_socket(response):
    return (getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            or getattr(getattr(response, "fp", None), "_sock", None))


class TransferDeadline:
    """Interrupt an active read on cancellation or the original total deadline."""
    def __init__(self, sock, deadline, cancelled):
        self.sock, self.deadline, self.cancelled = sock, deadline, cancelled
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._expired = False
        self._cancelled = False
        self._thread = None

    def _watch(self):
        while not self._done.wait(min(0.05, max(0.001, self.deadline - time.monotonic()))):
            with self._lock:
                if self._done.is_set():
                    return
                self._cancelled = self.cancelled.is_set()
                self._expired = time.monotonic() >= self.deadline
                if self._cancelled or self._expired:
                    try:
                        self.sock.shutdown(socket.SHUT_RDWR)
                    except (OSError, AttributeError):
                        pass
                    return

    def __enter__(self):
        if self.cancelled.is_set():
            raise VoiceDownloadCancelled()
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Voice download timed out")
        if self.sock is not None:
            self._thread = threading.Thread(target=self._watch, name="VoiceTransferDeadline", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, kind, value, traceback):
        with self._lock:
            self._done.set()
            self.sock = None
        if self._thread is not None:
            self._thread.join(0.2)
        if self._cancelled or self.cancelled.is_set():
            raise VoiceDownloadCancelled() from value
        if self._expired or time.monotonic() >= self.deadline:
            raise TimeoutError("Voice download timed out") from value


class VoiceHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, transfer_deadline, cancel_event, **kwargs):
        self.transfer_deadline, self.cancel_event = transfer_deadline, cancel_event
        super().__init__(*args, **kwargs)

    def getresponse(self):
        response = None
        try:
            deadline = min(self.transfer_deadline, time.monotonic() + VOICE_HEADER_SECONDS)
            with TransferDeadline(self.sock, deadline, self.cancel_event):
                response = super().getresponse()
            return response
        except BaseException:
            if response is not None:
                response.close()
            self.close()
            raise


class VoiceHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, deadline, cancelled):
        super().__init__()
        self.deadline, self.cancelled = deadline, cancelled

    def https_open(self, request):
        connection = partial(VoiceHTTPSConnection, transfer_deadline=self.deadline, cancel_event=self.cancelled)
        return self.do_open(connection, request, context=self._context)


def safe_voice(value):
    return value if isinstance(value, str) and value in VOICES else DEFAULT_VOICE


def bundled_directory():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / ".tools")) / "tts"


def cache_directory():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "SouthlandServers/SLS_Mass_Notify/voices"


def read_catalog(path=None):
    path = path or (bundled_directory() / "voices.json" if getattr(sys, "frozen", False)
                    else Path(__file__).resolve().parent.parent / "tools/piper-voices.json")
    if Path(path).stat().st_size > 64 * 1024:
        raise ValueError("Voice catalog exceeds its size limit")
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not re.fullmatch(r"[a-f0-9]{40}", str(catalog.get("revision", ""))):
        raise ValueError("Invalid voice catalog revision")
    files = catalog.get("files")
    expected = {voice + suffix for voice in VOICES for suffix in SUFFIXES}
    if not isinstance(files, list) or len(files) != len(expected):
        raise ValueError("Invalid voice catalog inventory")
    found = set()
    for entry in files:
        if not isinstance(entry, dict) or entry.get("name") not in expected or entry["name"] in found:
            raise ValueError("Invalid voice catalog filename")
        found.add(entry["name"])
        if (type(entry.get("size")) is not int or not 0 < entry["size"] <= 80 * 1024 * 1024
                or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256", "")))):
            raise ValueError("Invalid voice catalog integrity fields")
        url = urllib.parse.urlsplit(entry.get("url", ""))
        if (url.scheme != "https" or url.netloc != "huggingface.co" or url.query or url.fragment
                or not url.path.startswith("/rhasspy/piper-voices/resolve/" + catalog["revision"] + "/")):
            raise ValueError("Voice URL is outside the pinned source")
    return catalog


def matches(path, entry, *, verify=True):
    reject_reparse(path)
    if not path.is_file() or path.stat().st_size != entry["size"]:
        return False
    if not verify:
        return True
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == entry["sha256"]


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        host = url.hostname or ""
        trusted = host in {"huggingface.co", "hf.co"} or host.endswith((".huggingface.co", ".hf.co"))
        if url.scheme != "https" or not trusted or url.username or url.password or url.port not in (None, 443):
            raise ValueError("Voice download redirected outside its HTTPS source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class VoiceStore:
    def __init__(self, *, bundled=None, cache=None, catalog=None):
        self.bundled = Path(bundled) if bundled is not None else bundled_directory()
        self.cache = Path(cache) if cache is not None else cache_directory()
        self.catalog = catalog if catalog is not None else read_catalog()

    def entries(self, voice):
        if not isinstance(voice, str) or voice not in VOICES:
            raise ValueError("Unknown announcement voice")
        names = {voice + suffix for suffix in SUFFIXES}
        return [entry for entry in self.catalog["files"] if entry["name"] in names]

    def location(self, voice, *, verify=False):
        entries = self.entries(voice)
        for directory in (self.bundled, self.cache / voice):
            if all(matches(directory / entry["name"], entry, verify=verify) for entry in entries):
                return directory
        return None

    def model(self, voice):
        directory = self.location(voice, verify=True)
        if directory is None:
            raise ValueError("The announcement voice is missing or damaged; download it in Settings")
        return directory / (voice + ".onnx")

    def download(self, voice, cancelled, progress=lambda *_: None, *, opener=None):
        entries = self.entries(voice)
        reject_reparse(self.cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        target = self.cache / voice
        reject_reparse(target)
        total = sum(entry["size"] for entry in entries)
        completed = 0
        deadline = time.monotonic() + VOICE_DOWNLOAD_SECONDS
        # No PBX credentials, cookies, or announcement text enter these requests.
        opener = opener or urllib.request.build_opener(HTTPSRedirects(), VoiceHTTPSHandler(deadline, cancelled))
        temporary = Path(tempfile.mkdtemp(prefix=".download-", dir=self.cache))
        try:
            for entry in entries:
                if cancelled.is_set():
                    return False
                request = urllib.request.Request(entry["url"], headers={"User-Agent": "SLS-Mass-Notify-Voice-Download"})
                with opener.open(request, timeout=15) as response, \
                     TransferDeadline(transfer_socket(response), deadline, cancelled), \
                     (temporary / entry["name"]).open("wb") as output:
                    size = 0
                    while True:
                        if cancelled.is_set():
                            return False
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Voice download timed out")
                        block = response.read(128 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if size > entry["size"]:
                            raise ValueError("Voice download exceeded its pinned size")
                        output.write(block)
                        progress(completed + size, total)
                    output.flush()
                    os.fsync(output.fileno())
                if not matches(temporary / entry["name"], entry):
                    raise ValueError("Voice download failed its integrity check")
                completed += entry["size"]
            if cancelled.is_set():
                return False
            reject_reparse(target)
            target.mkdir(exist_ok=True)
            # Publish only after all three assets pass; model goes last. Readers
            # require every pinned file, so partial installations are never used.
            for entry in sorted(entries, key=lambda value: value["name"].endswith(".onnx")):
                destination = target / entry["name"]
                reject_reparse(destination)
                os.replace(temporary / entry["name"], destination)
            return True
        except VoiceDownloadCancelled:
            return False
        except urllib.error.HTTPError as error:
            error.close()
            raise
        finally:
            reject_reparse(temporary)
            shutil.rmtree(temporary)


def voice_available(voice):
    try:
        return VoiceStore().location(safe_voice(voice)) is not None
    except (OSError, ValueError):
        return False


def playback_voice(voice):
    return safe_voice(voice) if voice_available(voice) else DEFAULT_VOICE


class VoiceDownloads:
    """One explicit background download, with status polled by the Tk thread."""
    def __init__(self, store=None):
        self.store = store or VoiceStore()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self._status = {"voice": "", "state": "idle", "bytes": 0, "total": 0}

    def status(self):
        with self._lock:
            return dict(self._status)

    def start(self, voice):
        self.store.entries(voice)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._cancel = threading.Event()
            self._status = {"voice": voice, "state": "downloading", "bytes": 0,
                            "total": sum(e["size"] for e in self.store.entries(voice))}
            self._thread = threading.Thread(target=self._run, args=(voice,), name="VoiceDownload", daemon=True)
            self._thread.start()
        return True

    def _run(self, voice):
        def progress(done, total):
            with self._lock:
                self._status.update(bytes=done, total=total)
        try:
            success = self.store.download(voice, self._cancel, progress)
            state = "installed" if success else "cancelled"
        except Exception:
            state = "cancelled" if self._cancel.is_set() else "failed"
        with self._lock:
            self._status["state"] = state

    def cancel(self):
        self._cancel.set()
        with self._lock:
            if self._status["state"] == "downloading":
                self._status["state"] = "cancelling"
