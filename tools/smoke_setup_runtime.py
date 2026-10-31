"""Windows setup integration smoke: real harmless processes, hidden UI, temp files.

No production app, PBX, registry, shared shortcuts, elevation or Program Files mutation.
Windows privilege/registration boundaries are replaced with temporary fixtures;
process shutdown, file replacement, rollback infrastructure, and Tk are real.
"""
from contextlib import ExitStack
from functools import partial
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import json
import traceback
import tkinter as tk
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import sll_installer as installer
import sll_install_safety as safety
import sll_install_windows as windows


FIXTURE = r'''
using System;
using System.Diagnostics;
using System.Reflection;
using System.Threading;
class Fixture {
    static int Main(string[] args) {
        if (args.Length == 1 && args[0] == "--parent") {
            using (Process child = Process.Start(new ProcessStartInfo {
                FileName = Assembly.GetExecutingAssembly().Location,
                Arguments = "--child", UseShellExecute = false, CreateNoWindow = true
            })) { child.WaitForExit(); return child.ExitCode; }
        }
        Thread.Sleep(300000);
        return 0;
    }
}
'''


def main():
    full_payload = "--full-payload" in sys.argv
    # Read-only validation against the host's real Start Menu ACLs. Exercise
    # the directory helper too: checking only the link validator missed a
    # stricter ancestor check that rejected otherwise valid shell directories.
    for location in (installer.START_MENU_DIR, installer.STARTUP_DIR):
        existing = location
        while not existing.exists():
            existing = existing.parent
        installer.create_protected_directories(existing, allow_shell_delete=True)
    print("PASS: real shared Start Menu directory permissions (read-only).", flush=True)
    compiler = windows.system_directory().parent / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    fixture_parent = ROOT / "build"
    fixture_parent.mkdir(exist_ok=True)
    # Keep native fixture paths inside the workspace. A sandbox can permit the
    # short %TEMP% alias while denying expansion of its user-profile ancestor,
    # making the same executable appear to have two different image paths.
    with tempfile.TemporaryDirectory(prefix="sll-setup-smoke-", dir=fixture_parent) as directory:
        base = Path(directory).resolve()
        assert base.is_relative_to(fixture_parent.resolve())
        target, other = base / "installed", base / "unrelated"
        target.mkdir()
        other.mkdir()
        source = base / "Fixture.cs"
        source.write_text(FIXTURE, encoding="utf-8")
        executable = target / installer.EXE_NAME
        subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64",
                        "/out:" + str(executable), str(source)], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        replacement = ((ROOT / "dist" / "SLL_Mass_Notify" / installer.EXE_NAME).read_bytes()
                       if full_payload else executable.read_bytes() + b"replacement-build")
        other_exe = other / installer.EXE_NAME
        shutil.copy2(executable, other_exe)
        safety.write_json(target / safety.MANIFEST_NAME, safety.manifest_for(target, version="fixture-old"))
        (target / "customer-notes.txt").write_text("preserve", encoding="utf-8")
        app = unrelated = root = window = None
        try:
            app = subprocess.Popen([str(executable), "--parent"], creationflags=subprocess.CREATE_NO_WINDOW)
            unrelated = subprocess.Popen([str(other_exe), "--idle"], creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 10
            while len(windows.exact_processes(executable)) != 2:
                if time.monotonic() > deadline:
                    raise AssertionError("Fixture parent/child failed to start")
                time.sleep(0.05)
            assert not windows.terminate_exact_process(unrelated.pid, executable), "Cross-path process was authorized"
            assert unrelated.poll() is None
            assert windows.children_first(windows.exact_processes(executable), windows.process_parents())[-1] == app.pid
            shortcuts = {name: base / (name + ".lnk") for name in ("application", "uninstall", "startup")}
            real_stage_payload = installer.stage_payload

            def stage(path):
                if full_payload:
                    real_stage_payload(path)
                else:
                    (path / installer.EXE_NAME).write_bytes(replacement)
                    (path / "new-runtime.txt").write_text("new", encoding="utf-8")


            with ExitStack() as patches:
                if full_payload:
                    package = ROOT / "build" / "installer-payload" / "SLL_Mass_Notify_Installer"
                    patches.enter_context(mock.patch.object(installer.sys, "frozen", True, create=True))
                    patches.enter_context(mock.patch.object(installer.sys, "executable", str(package / "SLL_Mass_Notify_Installer.exe")))
                    patches.enter_context(mock.patch.object(installer.sys, "_MEIPASS", str(package / "_internal"), create=True))
                for name in ("require_admin", "verify_protected_directory", "protect_new_directory", "write_uninstall_registry", "restore_uninstall_registry"):
                    patches.enter_context(mock.patch.object(installer, name))
                patches.enter_context(mock.patch.object(installer, "registered_install_dir", return_value=target))
                patches.enter_context(mock.patch.object(installer, "validate_install_dir", side_effect=lambda path, **_: path))
                patches.enter_context(mock.patch.object(installer, "snapshot_uninstall_registry", return_value=None))
                patches.enter_context(mock.patch.object(installer, "machine_shortcuts", return_value=shortcuts))
                patches.enter_context(mock.patch.object(installer, "stage_payload", side_effect=stage))
                patches.enter_context(mock.patch.object(installer, "close_exact_processes", side_effect=partial(windows.close_exact_processes, timeout=0.3)))
                success = patches.enter_context(mock.patch.object(installer.messagebox, "showinfo"))
                failure = patches.enter_context(mock.patch.object(installer.messagebox, "showerror", side_effect=lambda *a, **k: root.quit()))
                root = tk.Tk()
                root.withdraw()
                window = installer.InstallerWindow(root)
                finished = window.operation.finished
                def report_finished(result, error):
                    if error is not None:
                        # Preserve the original failure when rollback itself
                        # fails; the message box shows only the last exception.
                        traceback.print_exception(error, chain=True)
                    return finished(result, error)
                window.operation.finished = report_finished
                report_progress = window.operation.progress
                def report_step(message):
                    print("SETUP: " + message, flush=True)
                    report_progress(message)
                window.operation.progress = report_step
                window.accept_terms.set(True)
                window.launch.set(False)
                window.startup.set(False)
                ticks = []
                timeout_fired = []
                def heartbeat():
                    ticks.append(time.monotonic())
                    root.after(10, heartbeat)
                def timed_out():
                    timeout_fired.append(True)
                    root.quit()
                root.after(10, heartbeat)
                root.after(120000 if full_payload else 15000, timed_out)
                window.install()
                window.install()  # Duplicate clicks cannot start another transaction.
                root.mainloop()
                if window.operation.thread:
                    window.operation.thread.join(5)
                assert not failure.called, str(failure.call_args)
                assert not timeout_fired, "Setup did not complete within the integration-test deadline"
                assert success.call_count == 1 and not failure.called, str(failure.call_args)
                assert len(ticks) >= 10, "Tk did not keep processing timer events during installation"
                assert windows.exact_processes(executable) == []
                assert app.wait(timeout=5) == 0
                assert unrelated.poll() is None, "An unrelated copy was stopped"
                assert executable.read_bytes() == replacement
                assert (target / "customer-notes.txt").read_text() == "preserve"
                assert safety.read_manifest(target)["version"] == installer.APP_VERSION
                assert windows.normalized_image_path(windows.shortcut_identity(shortcuts["application"])["target"]) == windows.normalized_image_path(executable)
                uninstall_link = windows.shortcut_identity(shortcuts["uninstall"])
                assert uninstall_link["arguments"] == "--uninstall"
                if full_payload:
                    expected_uninstaller = target / installer.MAINTENANCE_DIR / "SLL_Mass_Notify_Installer.exe"
                    assert windows.normalized_image_path(uninstall_link["target"]) == windows.normalized_image_path(expected_uninstaller)
                    assert expected_uninstaller.is_file(), "Uninstall shortcut points to a missing runtime"
                assert not shortcuts["startup"].exists()
                print("PASS: " + ("complete packaged payload upgrade, " if full_payload else "")
                      + "real stuck parent/child shutdown, same-name other-path protection, responsive hidden setup UI, native shell links, file replacement and preserved unrelated content.")
        finally:
            if window is not None and window.operation.thread is not None:
                window.operation.thread.join(10)
            if root is not None:
                try:
                    root.destroy()
                except tk.TclError:
                    pass
            for path in (executable, other_exe):
                for pid in windows.exact_processes(path):
                    windows.terminate_exact_process(pid, path)
            for process in (app, unrelated):
                if process is not None:
                    process.wait(timeout=5)


def check_file_upgrade():
    """Exercise the complete large payload in a fixture, with no UI or OS writes."""
    package = ROOT / "build" / "installer-payload" / "SLL_Mass_Notify_Installer"
    with tempfile.TemporaryDirectory(prefix="sll-file-upgrade-", dir=ROOT / "build") as directory:
        base = Path(directory).resolve()
        assert base.is_relative_to((ROOT / "build").resolve())
        target = base / "installed"
        links = {key: base / (key + ".lnk") for key in ("application", "uninstall", "startup")}
        transactions, phases = [], []
        transaction_class = safety.FileTransaction
        def transaction(*args, **kwargs):
            result = transaction_class(*args, **kwargs)
            transactions.append(result)
            return result
        with ExitStack() as patches:
            patches.enter_context(mock.patch.object(installer.sys, "frozen", True, create=True))
            patches.enter_context(mock.patch.object(installer.sys, "executable", str(package / "SLL_Mass_Notify_Installer.exe")))
            patches.enter_context(mock.patch.object(installer.sys, "_MEIPASS", str(package / "_internal"), create=True))
            installer.stage_payload(target)
            with (target / installer.EXE_NAME).open("ab") as output:
                output.write(b"fixture previous application")
            safety.write_json(target / installer.DEFAULTS_NAME, {"startup_enabled": True, "auto_update_enabled": False})
            safety.write_json(target / safety.MANIFEST_NAME, safety.manifest_for(target, version="fixture-previous"))
            (target / "customer-notes.txt").write_text("preserve", encoding="utf-8")
            models = {path.relative_to(target).as_posix(): path.stat().st_ino
                      for path in (target / "_internal" / "tts").glob("*.onnx")}
            assert list(models) == ["_internal/tts/en_US-lessac-low.onnx"]
            for name in ("require_admin", "verify_protected_directory", "protect_new_directory",
                         "create_protected_directories", "write_uninstall_registry", "restore_uninstall_registry", "stop_running_app"):
                patches.enter_context(mock.patch.object(installer, name))
            patches.enter_context(mock.patch.object(installer, "validate_install_dir", side_effect=lambda path, **_: path))
            patches.enter_context(mock.patch.object(installer, "snapshot_uninstall_registry", return_value=None))
            patches.enter_context(mock.patch.object(installer, "machine_shortcuts", return_value=links))
            patches.enter_context(mock.patch.object(installer, "create_shortcut", side_effect=lambda path, dest, **_: path.write_text(str(dest), encoding="utf-8")))
            patches.enter_context(mock.patch.object(installer, "FileTransaction", side_effect=transaction))
            started = time.perf_counter()
            installer.install_app(target, startup=None, auto_update=None, launch=False, remove_legacy=False,
                                  progress=lambda message: phases.append((message, round(time.perf_counter() - started, 3))))
            elapsed = round(time.perf_counter() - started, 3)
        manifest = safety.read_manifest(target)
        assert manifest["version"] == installer.APP_VERSION
        assert transactions[0].changes == [installer.EXE_NAME], transactions[0].changes
        assert all((target / name).stat().st_ino == identity for name, identity in models.items())
        assert all(safety.digest(target / name) == expected for name, expected in manifest["files"].items())
        assert (target / "customer-notes.txt").read_text(encoding="utf-8") == "preserve"
        assert not (target / safety.TRANSACTION_NAME).exists()
        print(json.dumps({"file_upgrade_seconds": elapsed, "owned_files_verified": len(manifest["files"]),
                          "models_kept_in_place": len(models), "files_replaced": len(transactions[0].changes),
                          "phases": phases, "scope": "Temporary fixture only; no UI, registry, production processes or Program Files writes"}), flush=True)


if __name__ == "__main__":
    if "--files-only" in sys.argv:
        check_file_upgrade()
    else:
        main()
