"""One hidden, reusable Piper process; private bounded file requests only."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time


def speech_command(*arguments):
    executable, environment = sys.executable, None
    command = []
    if not getattr(sys, "frozen", False):
        # Match multiprocessing's Windows venv handling. Killing a venv
        # redirector would otherwise leave the actual interpreter running.
        if os.name == "nt" and sys.prefix != sys.base_prefix:
            executable = sys._base_executable
            environment = dict(os.environ, __PYVENV_LAUNCHER__=sys.executable)
        command.append(str(Path(__file__).with_name("sll_mass_notify.py")))
    return [executable, *command, *map(str, arguments)], environment


def write_message(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def read_message(path):
    with path.open("rb") as stream:
        data = stream.read(16 * 1024 + 1)
    if len(data) > 16 * 1024:
        raise ValueError("Speech worker message exceeds its limit")
    return json.loads(data)


def watch_parent(identifier):
    """Exit if the owning app dies, including while Piper is synthesizing."""
    if not 0 < identifier < 2**32 or identifier == os.getpid():
        raise ValueError("Invalid speech worker owner")
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        handle = kernel.OpenProcess(0x100000, False, identifier)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        def wait():
            # The handle lives for this process's lifetime and cannot follow a
            # reused PID. Windows closes it when this helper exits.
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(0)
    else:
        def wait():
            while os.getppid() == identifier:
                time.sleep(0.2)
            os._exit(0)
    threading.Thread(target=wait, name="SpeechOwner", daemon=True).start()


def run_worker(directory, owner):
    from sll_speech import load_voice, write_speech, validate_speech_request
    directory = Path(directory)
    watch_parent(owner)
    startup = read_message(directory / "startup.json")
    voice, _ = validate_speech_request(startup)
    try:
        engine = load_voice(voice)
        write_speech(engine, "Ready.", directory / "speech.wav")
        (directory / "speech.wav").unlink()
    except Exception as exc:
        write_message(directory / "ready.json", {"ok": False, "error": type(exc).__name__})
        return
    write_message(directory / "ready.json", {"ok": True, "voice": voice, "pid": os.getpid()})
    previous = ""
    while directory.is_dir():
        request_path = directory / "request.json"
        if not request_path.exists():
            time.sleep(0.025)
            continue
        request = read_message(request_path)
        identifier = request.get("id") if isinstance(request, dict) else None
        if (not isinstance(identifier, str) or len(identifier) != 32
                or any(character not in "0123456789abcdef" for character in identifier)):
            raise ValueError("Invalid speech request identity")
        if identifier == previous:
            time.sleep(0.025)
            continue
        previous = identifier
        try:
            _, text = validate_speech_request(dict(request, voice=voice))
            write_speech(engine, text, directory / "speech.wav")
            result = {"id": identifier, "ok": True}
        except Exception as exc:
            result = {"id": identifier, "ok": False, "error": type(exc).__name__}
        finally:
            request_path.unlink(missing_ok=True)
        write_message(directory / "result.json", result)


class PiperWorker:
    def __init__(self):
        self._operation = threading.Lock()
        self._state = threading.Lock()
        self._closed = threading.Event()
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self._process = self._directory = self._voice = None
        self._warming = False
        self._wanted_voice = None

    def _reset(self):
        with self._state:
            process, directory = self._process, self._directory
            self._process = self._directory = self._voice = None
            self.ready.clear()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        if directory is not None:
            directory.cleanup()

    def _ensure(self, voice, cancelled, *, deadline=None):
        from sll_speech import SYNTHESIS_TIMEOUT
        if self._closed.is_set() or cancelled.is_set():
            return False
        if (self._process is not None and self._process.poll() is None
                and self._voice == voice and self.ready.is_set()):
            return True
        self._reset()
        if self._closed.is_set() or cancelled.is_set():
            return False
        directory = tempfile.TemporaryDirectory(prefix="sll-piper-")
        base = Path(directory.name)
        write_message(base / "startup.json", {"voice": voice, "text": "Ready."})
        command, environment = speech_command("--speech-worker", base, os.getpid())
        try:
            process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except BaseException:
            directory.cleanup()
            raise
        with self._state:
            self._process, self._directory, self._voice = process, directory, voice
        deadline = time.monotonic() + SYNTHESIS_TIMEOUT if deadline is None else deadline
        while not self._closed.is_set() and not cancelled.is_set():
            if process.poll() is not None:
                raise RuntimeError("Piper worker exited during initialization")
            if (base / "ready.json").exists():
                result = read_message(base / "ready.json")
                if result.get("ok") is not True or result.get("voice") != voice:
                    raise RuntimeError("Piper voice could not be initialized")
                self.ready.set()
                return True
            if time.monotonic() >= deadline:
                raise TimeoutError("Piper initialization timed out")
            cancelled.wait(0.025)
        return False

    def prewarm(self, voice):
        with self._state:
            self._wanted_voice = voice
            if self._warming or self._closed.is_set():
                return
            self._warming = True

        def warm():
            try:
                from sll_voices import playback_voice
                while True:
                    with self._state:
                        if self._closed.is_set():
                            self._warming = False
                            return
                        requested = self._wanted_voice
                    with self._operation:
                        try:
                            self._ensure(playback_voice(requested), self._closed)
                        except Exception:
                            self._reset()
                    with self._state:
                        if requested == self._wanted_voice:
                            self._warming = False
                            return
            except Exception:
                with self._state:
                    self._warming = False
        threading.Thread(target=warm, name="PiperWarmup", daemon=True).start()

    def synthesize(self, text, output, cancelled, voice):
        from sll_speech import SYNTHESIS_TIMEOUT
        from sll_audio import copy_validated_audio
        deadline = time.monotonic() + SYNTHESIS_TIMEOUT
        while not self._operation.acquire(timeout=0.025):
            if self._closed.is_set() or cancelled.is_set():
                return False
            if time.monotonic() >= deadline:
                raise TimeoutError("Piper initialization timed out")
        try:
            if self._closed.is_set() or cancelled.is_set():
                return False
            if not self._ensure(voice, cancelled, deadline=deadline):
                self._reset()
                return False
            base = Path(self._directory.name)
            identifier = secrets.token_hex(16)
            write_message(base / "request.json", {"id": identifier, "text": text})
            while not self._closed.is_set() and not cancelled.is_set():
                if self._process.poll() is not None:
                    raise RuntimeError("Piper worker exited during synthesis")
                result_path = base / "result.json"
                if result_path.exists():
                    result = read_message(result_path)
                    if result.get("id") == identifier:
                        result_path.unlink()
                        if result.get("ok") is not True:
                            raise RuntimeError("Piper could not synthesize this notification")
                        copy_validated_audio(base / "speech.wav", output)
                        (base / "speech.wav").unlink()
                        return not cancelled.is_set() and not self._closed.is_set()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Piper synthesis timed out")
                cancelled.wait(0.025)
            self._reset()
            return False
        except BaseException:
            self._reset()
            raise
        finally:
            self._operation.release()

    def close(self):
        with self._state:
            if self._closed.is_set():
                return
            self._closed.set()
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass  # The worker may already have exited.

        def cleanup():
            try:
                with self._operation:
                    self._reset()
            finally:
                self.stopped.set()
        threading.Thread(target=cleanup, name="PiperCleanup", daemon=True).start()
