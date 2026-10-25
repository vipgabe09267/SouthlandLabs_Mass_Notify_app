"""Run real Windows UI fixtures on a private desktop without switching the screen.

No production app, PBX, registry or shared shortcut is changed. Each fixture runs
in its own process job; closing the job terminates only that fixture's children.
"""
import ctypes
import argparse
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ("smoke_window_layout.py", "smoke_notification_delivery.py",
          "smoke_announcement_layout.py", "smoke_setup_runtime.py")


class StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
                ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR),
                ("x", wintypes.DWORD), ("y", wintypes.DWORD), ("width", wintypes.DWORD),
                ("height", wintypes.DWORD), ("xchars", wintypes.DWORD), ("ychars", wintypes.DWORD),
                ("fill", wintypes.DWORD), ("flags", wintypes.DWORD), ("show", wintypes.WORD),
                ("reserved_size", wintypes.WORD), ("reserved_bytes", ctypes.c_void_p),
                ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


def run_check(kernel, desktop_name, wrapper, name, output, timeout=180, *, application=None):
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    process = ProcessInfo()
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.desktop = desktop_name
        startup.flags = 1
        startup.show = 0
        executable = str(application) if application else sys.executable
        arguments = ([executable, "--check-presentation"] if application else
                     [executable, str(wrapper), str(ROOT / "tools" / name), str(output)])
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
        # CREATE_SUSPENDED ensures no fixture code executes before containment.
        if not kernel.CreateProcessW(executable, command, None, None, False, 0x08000004,
                                     None, str(ROOT), ctypes.byref(startup), ctypes.byref(process)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job, process.process):
            kernel.TerminateProcess(process.process, 1)
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        status = kernel.WaitForSingleObject(process.process, int(timeout * 1000))
        if status == 0x102:
            raise TimeoutError(f"Private desktop fixture timed out: {name}; see {output}")
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(process.process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value:
            raise RuntimeError(f"Private desktop fixture failed ({code.value}): {name}; see {output}")
    finally:
        kernel.CloseHandle(job)
        for handle in (process.thread, process.process):
            if handle:
                kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, help="Also check the packaged app on the private desktop")
    arguments = parser.parse_args()
    application = arguments.application.resolve(strict=True) if arguments.application else None
    if application is not None and (not application.is_file() or application.name != "SLS_Mass_Notify.exe"):
        raise SystemExit("Application must be the packaged SLS_Mass_Notify.exe")
    if os.name != "nt":
        raise SystemExit("Private desktop validation requires Windows.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    signatures = (
        (kernel.CreateJobObjectW, [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        (kernel.SetInformationJobObject, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        (kernel.AssignProcessToJobObject, [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        (kernel.CreateProcessW, [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                               wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                               ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo)], wintypes.BOOL),
        (kernel.ResumeThread, [wintypes.HANDLE], wintypes.DWORD),
        (kernel.TerminateProcess, [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        (kernel.WaitForSingleObject, [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        (kernel.GetExitCodeProcess, [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (kernel.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
        (user.CreateDesktopW, [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p], wintypes.HANDLE),
        (user.CloseDesktop, [wintypes.HANDLE], wintypes.BOOL),
    )
    for function, args, result in signatures:
        function.argtypes, function.restype = args, result
    desktop_name = "SLSAudit_" + uuid.uuid4().hex
    desktop = user.CreateDesktopW(desktop_name, None, None, 0, 0x10000000, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    output = ROOT / "build" / "isolated-ui"
    output.mkdir(parents=True, exist_ok=True)
    wrapper = output / "runner.py"
    wrapper.write_text(
        "import contextlib, os, runpy, sys, traceback\n"
        "from pathlib import Path\n"
        "tool, output = map(Path, sys.argv[1:3])\n"
        "root = tool.parent.parent\n"
        "sys.path[:0] = [str(root / 'src'), str(root / 'tools')]\n"
        "os.environ['TCL_LIBRARY'] = str(root / 'build/tk-data/tcl_library')\n"
        "os.environ['TK_LIBRARY'] = str(root / 'build/tk-data/tk_library')\n"
        "sys.argv = [str(tool)]\n"
        "with output.open('w', encoding='utf-8', buffering=1) as log:\n"
        "    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):\n"
        "        try:\n"
        "            runpy.run_path(str(tool), run_name='__main__')\n"
        "        except BaseException:\n"
        "            traceback.print_exc()\n"
        "            raise SystemExit(1)\n", encoding="utf-8")
    try:
        for name in CHECKS:
            started = time.monotonic()
            run_check(kernel, desktop_name, wrapper, name, output / (Path(name).stem + ".log"))
            print(f"PASS {name}: {time.monotonic() - started:.1f}s on private desktop", flush=True)
        if application is not None:
            output_path = output / "packaged-presentation.log"
            output_path.write_text("Running packaged native overlay and label checks on a private desktop.\n", encoding="utf-8")
            run_check(kernel, desktop_name, wrapper, "packaged presentation", output_path, application=application)
            with output_path.open("a", encoding="utf-8") as log:
                log.write("PASS: packaged presentation exited successfully.\n")
            print("PASS packaged presentation: always-on-top, native z-order, labels, image/plain layout and Dismiss", flush=True)
    finally:
        user.CloseDesktop(desktop)
    print("All UI fixtures passed without switching or displaying on the input desktop.")


if __name__ == "__main__":
    main()
