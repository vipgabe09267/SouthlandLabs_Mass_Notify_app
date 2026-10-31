"""Invisible native Windows layout checks; no settings writes or PBX connections."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import sll_mass_notify as client
import sll_installer as installer
from sll_windowing import fit_window, monitor_work_area
from sll_theme import configure_theme


def contrast(window, first, second):
    def luminance(color):
        channels = [value / 65535 for value in window.winfo_rgb(color)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def check_text_controls(window):
    """Inspect actual widget states; catch the dark-theme invisible-caret bug."""
    style = ttk.Style(window)
    entries = []
    def check(widget):
        kind = widget.winfo_class()
        if kind in ("TEntry", "TCombobox", "TSpinbox"):
            name = widget.cget("style") or kind
            state = tuple(widget.state())
            field = style.lookup(name, "fieldbackground", state)
            caret = style.lookup(name, "insertcolor", state)
            assert contrast(window, field, caret) >= 7, (kind, state, field, caret)
            assert int(style.lookup(name, "insertwidth", state)) >= 2
            assert str(widget.cget("cursor")) == "xterm", (kind, widget.cget("cursor"))
            if kind == "TEntry" and not widget.instate(("disabled",)):
                entries.append(widget)
        elif kind == "Text":
            assert contrast(window, widget.cget("background"), widget.cget("insertbackground")) >= 7
            assert int(widget.cget("insertwidth")) >= 2
        for child in widget.winfo_children():
            check(child)
    check(window)
    for entry in entries:
        original = entry.get()
        entry.delete(0, "end")
        entry.insert(0, "Caret check")
        entry.icursor(5)
        assert entry.index("insert") == 5
        entry.selection_range(0, 5)
        assert entry.selection_present()
        entry.selection_clear()
        entry.delete(0, "end")
        entry.insert(0, original)
    return len(entries)


def widgets(window):
    for child in window.winfo_children():
        yield child
        yield from widgets(child)


def check_settings_header(settings):
    assert settings.logo_image is not None, "Official app artwork did not load"
    assert settings.logo_image.width() > 0 and settings.logo_image.height() > 0
    labels = [widget for widget in widgets(settings.window) if widget.winfo_class() == "TLabel"]
    logo = next(widget for widget in labels if widget.cget("style") == "Logo.TLabel")
    title = next(widget for widget in labels if widget.cget("style") == "Header.TLabel")
    assert title.cget("text") == "Southland Labs Mass Notify"
    for label in labels:
        if label.cget("style") in {"Logo.TLabel", "Header.TLabel", "HeaderHint.TLabel",
                                    "Version.TLabel", "BadgeOn.TLabel", "BadgeOff.TLabel"}:
            check_control(settings.window, label)
            assert label.winfo_width() >= label.winfo_reqwidth(), (
                label.cget("style"), label.winfo_width(), label.winfo_reqwidth())
            assert label.winfo_height() >= label.winfo_reqheight()
    check_control(settings.window, logo)


def check_password_masking(settings):
    for index, form in enumerate(settings.endpoint_forms):
        entry = form["password_entry"]
        assert entry.cget("show") == "*", "Password was exposed by default"
        form["show_password"].set(True)
        settings.toggle_password(index)
        assert entry.cget("show") == ""
        form["show_password"].set(False)
        settings.toggle_password(index)
        assert entry.cget("show") == "*", "Password was not masked again"


def check_combobox_states(window):
    """Typing works only in editable mode; readonly/disabled modes stay safe."""
    holder = ttk.Frame(window)
    holder.pack()
    combo = ttk.Combobox(holder, values=("First voice", "Second voice"), state="normal")
    combo.pack()
    combo.insert(0, "Editable input")
    combo.icursor(5)
    assert combo.get() == "Editable input" and combo.index("insert") == 5
    combo.configure(state="readonly")
    combo.current(0)
    combo.insert(0, "Unexpected edit")
    assert combo.get() == "First voice" and combo.instate(("readonly",))
    combo.configure(state="disabled")
    combo.delete(0, "end")
    assert combo.get() == "First voice" and combo.instate(("disabled",))
    check_text_controls(holder)
    holder.destroy()


def check_bounds(window, area):
    window.deiconify()
    fit_window(window, (1140, 840), area=area)
    window.update()
    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    rect = wintypes.RECT()
    assert user.GetWindowRect(user.GetAncestor(window.winfo_id(), 2), ctypes.byref(rect))
    assert rect.left >= area[0] and rect.top >= area[1], (rect.left, rect.top, area)
    assert rect.right <= area[2] and rect.bottom <= area[3], (rect.right, rect.bottom, area)


def check_control(window, control):
    assert control.winfo_ismapped()
    assert control.winfo_rooty() >= window.winfo_rooty()
    assert control.winfo_rooty()+control.winfo_height() <= window.winfo_rooty()+window.winfo_height()
    assert control.winfo_rootx()+control.winfo_width() <= window.winfo_rootx()+window.winfo_width()


def main():
    with tempfile.TemporaryDirectory(prefix="sll-layout-") as directory:
        for scaling, compact in ((dpi / 72, compact) for dpi in (96, 120, 144, 192)
                                  for compact in (False, True)):
            root = tk.Tk()
            root.withdraw()
            root.attributes("-alpha", 0.0)
            root.tk.call("tk", "scaling", scaling)
            left, top, right, bottom = monitor_work_area(root)
            area = ((left, top, min(right, left+800), min(bottom, top+560))
                    if compact else (left, top, right, bottom))
            try:
                with mock.patch.object(installer, "registered_install_dir", return_value=Path(directory)/"installed"), \
                     mock.patch.object(installer, "saved_machine_preference", side_effect=lambda _, default: default):
                    setup = installer.InstallerWindow(root)
                check_bounds(root, area)
                check_control(root, setup.install_button)
                check_control(root, setup.cancel_button)
                assert check_text_controls(root) >= 1
                setup.body.canvas.yview_moveto(1)
                root.update()
                assert setup.body.canvas.yview()[1] > .99
            finally:
                root.destroy()
            root = tk.Tk()
            root.withdraw()
            root.tk.call("tk", "scaling", scaling)
            real_toplevel = tk.Toplevel
            def invisible(*args, **kwargs):
                result = real_toplevel(*args, **kwargs)
                result.withdraw()
                result.attributes("-alpha", 0.0)
                return result
            app = mock.Mock(root=root, status_text="Checking delivery.")
            app.voice_downloads.status.return_value = {"voice": "", "state": "idle", "bytes": 0, "total": 0}
            app.get_config.return_value = client.normalize_config({"enabled": False})
            try:
                with mock.patch.object(client, "Toplevel", side_effect=invisible):
                    settings = client.SettingsWindow(app)
                check_bounds(settings.window, area)
                check_control(settings.window, settings.test_button)
                check_control(settings.window, settings.status_label)
                assert check_text_controls(settings.window) >= 12
                check_settings_header(settings)
                check_password_masking(settings)
                with mock.patch.object(client, "Toplevel", side_effect=invisible):
                    toast = client.FaultToast(app, "The PBX connection is unavailable. Saved receipts will retry automatically when the network returns.")
                toast.window.update()
                work = monitor_work_area(root, primary=True)
                user = ctypes.windll.user32
                rect = wintypes.RECT()
                handle = user.GetAncestor(toast.window.winfo_id(), 2)
                assert user.GetWindowRect(handle, ctypes.byref(rect))
                assert abs(rect.right - (work[2]-12)) <= 1, (rect.right, work)
                assert abs(rect.bottom - (work[3]-12)) <= 1, (rect.bottom, work)
                assert rect.left >= work[0] and rect.top >= work[1]
                for widget in toast.window.winfo_children()[1].winfo_children()[-1].winfo_children():
                    check_control(toast.window, widget)
                toast.hide()
            finally:
                root.destroy()
    # History can be opened before Settings; it must receive the same readable
    # search field, caret, selection, and details colors without that side effect.
    root = tk.Tk()
    root.withdraw()
    configure_theme(root)
    check_combobox_states(root)
    presenter = client.AlertPresenter(root, lambda *_: None, lambda *_: None, lambda *_: None)
    try:
        presenter.show_history([{"title": "History fixture", "body": "Fixture details", "state": "dismissed"}])
        root.update()
        assert check_text_controls(presenter._history_window) == 1
    finally:
        presenter.shutdown()
        root.destroy()
    print("PASS: native Settings/setup fit at 100/125/150/200% scaling in full and compact work areas; header artwork/title, masked passwords, editable/readonly/disabled inputs and History search are readable; fault notices sit bottom-right above the taskbar.")


if __name__ == "__main__":
    main()
