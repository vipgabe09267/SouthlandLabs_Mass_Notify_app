"""Offline native presentation self-check for the packaged Windows runtime."""
import io
import os
from pathlib import Path
import threading
import time
import tkinter as tk
from types import SimpleNamespace

from PIL import Image

from sls_presentation import PendingAlert, _AlertView, presentation_policy
from sls_windowing import apply_window_icon


def assert_notification_overlay(window):
    """Check native topmost state and z-order above a newly raised normal app."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetAncestor.argtypes, user.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
    user.GetWindowLongPtrW.argtypes, user.GetWindowLongPtrW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
    handle = user.GetAncestor(window.winfo_id(), 2)
    assert user.GetWindowLongPtrW(handle, -20) & 0x8, "Notification lacks native always-on-top state"
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
        wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.GetTopWindow.argtypes, user.GetTopWindow.restype = [wintypes.HWND], wintypes.HWND
    user.GetWindow.argtypes, user.GetWindow.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.DestroyWindow.argtypes = [wintypes.HWND]
    other = user.CreateWindowExW(0x08000000, "STATIC", "Normal application fixture", 0x10CF0000,
                                 40, 40, 700, 500, None, None, None, None)
    if not other:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # Raise a normal top-level window after the notification was displayed.
        # NOACTIVATE avoids changing input focus, even on the private desktop.
        for state in (1, 3):  # Normal and maximized application windows.
            user.ShowWindow(other, state)
            if not user.SetWindowPos(other, None, 0, 0, 0, 0, 0x1 | 0x2 | 0x10):
                raise ctypes.WinError(ctypes.get_last_error())
            order = {}
            current = user.GetTopWindow(None)
            for index in range(1000):
                if not current:
                    break
                if current in (handle, other):
                    order[current] = index
                current = user.GetWindow(current, 2)
            assert handle in order and other in order, "Native overlay windows are missing from z-order"
            assert order[handle] < order[other], "A normal or maximized application covered the notification"
    finally:
        user.DestroyWindow(other)


def check_presentation(configure_style):
    for kind in ("announcement", "alert"):
        _check_visual_notification(configure_style, kind)
        _check_regular_text_notification(configure_style, kind)


def _check_regular_text_notification(configure_style, kind):
    root = tk.Tk()
    root.withdraw()
    configure_style(SimpleNamespace(window=root))
    view = None
    responses = []
    try:
        presenter = SimpleNamespace(root=root, image_loader=None,
            _respond=lambda *args: responses.append(args), show_history=lambda: None)
        alert = dict(kind=kind, title="Regular notification", body="Fixture instructions", priority="notice")
        policy = presentation_policy(alert)
        assert not policy.persistent, "Overlay must not change regular dismissal policy"
        view = _AlertView(presenter, PendingAlert("plain-fixture", alert, 0, policy), 0)
        view.window.attributes("-alpha", 0.0)
        root.update()
        assert_notification_overlay(view.window)
        assert view.urgency_label.cget("text") == "Regular"
        assert view.ack.cget("text") == "Dismiss"
        view.ack.invoke()
        assert responses == [("plain-fixture", "dismissed")]
    finally:
        if view is not None:
            view.close()
        root.destroy()


def _check_visual_notification(configure_style, kind):
    """Use real asynchronous image loading and the app theme, without user data."""
    root = tk.Tk()
    root.withdraw()
    apply_window_icon(root)
    configure_style(SimpleNamespace(window=root))
    data = io.BytesIO()
    Image.new("RGB", (480, 272), "#d42c41").save(data, format="PNG")
    ready = threading.Event()
    finished = threading.Event()
    view = None
    try:
        def image_loader(_alert):
            if not ready.wait(5):
                raise RuntimeError("Image self-check timed out")
            return data.getvalue()

        presenter = SimpleNamespace(root=root, image_loader=image_loader,
                                    _image_slots=threading.BoundedSemaphore(2),
                                    _respond=lambda *_: None, show_history=lambda: None)
        alert = dict(kind=kind, title="Local presentation check", body="Fixture instructions",
                     image_url="https://fixture.invalid/announcement.png",
                     severity="Severe" if kind == "alert" else "notice")
        view = _AlertView(presenter, PendingAlert("fixture", alert, 0, presentation_policy(alert)), 0)
        view.window.attributes("-alpha", 0.0)
        root.update()
        assert_notification_overlay(view.window)
        assert view.urgency_label.cget("text") == ("URGENT" if kind == "alert" else "Regular")
        assert view.instructions.winfo_ismapped(), "Initial text fallback is hidden"
        deadline = time.monotonic() + 5

        def poll():
            view.poll_image()
            if view._image_ref is not None or time.monotonic() >= deadline:
                finished.set()
                root.quit()
            else:
                root.after(25, poll)

        # Finish the download after Tk has mapped the text and entered its event loop.
        root.after(250, ready.set)
        root.after(275, poll)
        root.mainloop()
        root.update_idletasks()
        assert finished.is_set() and view._image_ref is not None, "Delayed image did not render"
        assert view.image_canvas.winfo_ismapped(), "Delayed image canvas is hidden"
        assert view.image_canvas.find_withtag("announcement"), "Image canvas is empty"
        assert not view.instructions.winfo_ismapped(), "Duplicate text remains visible"
        assert view.ack.winfo_ismapped()
        assert view.ack.cget("text") == ("I have read this alert" if kind == "alert" else "Dismiss")
        assert view.ack.winfo_rooty() + view.ack.winfo_height() <= view.window.winfo_rooty() + view.window.winfo_height()
        for window in (root, view.window):
            assert Path(getattr(window, "_sls_icon_path", "")).name == "favicon.ico", "SLS icon is not set on the window"
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                user = ctypes.windll.user32
                user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user.GetAncestor.restype = wintypes.HWND
                user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user.SendMessageW.restype = ctypes.c_ssize_t
                handle = user.GetAncestor(window.winfo_id(), 2)
                for icon_size in (0, 1):
                    assert user.SendMessageW(handle, 0x7F, icon_size, 0), "Native window icon is missing"
        view.window.geometry("560x380")
        root.update()
        assert view.image_canvas.winfo_ismapped() and view._image_ref.width() > 1
        assert view._image_ref.width() <= view.image_canvas.winfo_width()
        assert view._image_ref.height() <= view.image_canvas.winfo_height()
    finally:
        ready.set()
        if view is not None:
            view.close()
        root.destroy()
