import ctypes
import os
import unittest
from unittest.mock import Mock, patch

import sll_tray


class TrayPolicyTests(unittest.TestCase):
    def test_tooltip_contains_state_without_controls(self):
        value = sll_tray.status_tooltip("degraded", "PBX 2\nconnection\x00 failed")
        self.assertIn("Degraded", value)
        self.assertIn("PBX 2 connection failed", value)
        self.assertNotIn("\n", value)
        self.assertNotIn("\x00", value)

    def test_tooltip_fits_utf16_buffer_without_splitting_surrogate(self):
        value = sll_tray.status_tooltip("healthy", "🛑" * 200)
        self.assertLessEqual(len(value.encode("utf-16-le")), 254)
        self.assertIn("?", sll_tray.status_tooltip("healthy", "invalid \ud800"))

    def test_version_four_callbacks_decode_low_word(self):
        self.assertEqual(sll_tray.callback_action((1 << 16) | sll_tray.NIN_KEYSELECT), "open")
        self.assertEqual(sll_tray.callback_action((1 << 16) | sll_tray.WM_CONTEXTMENU), "menu")
        self.assertIsNone(sll_tray.callback_action(0x0200))

    def test_updates_post_to_native_thread_and_coalesce(self):
        callbacks = [Mock() for _ in range(4)]
        tray = sll_tray.TrayIcon(*callbacks)
        tray._api = Mock()
        tray._hwnd = 123
        tray.update("healthy", "All profiles connected")
        tray.update("degraded", "PBX 2 disconnected")
        tray._api.user32.PostMessageW.assert_called_once_with(123, sll_tray.WM_REFRESH, 0, 0)
        self.assertEqual(tray._status, "degraded")
        for callback in callbacks:
            callback.assert_not_called()

    def test_invalid_state_rejected(self):
        tray = sll_tray.TrayIcon(Mock(), Mock(), Mock(), Mock())
        with self.assertRaises(ValueError):
            tray.update("everything fine")

    def test_callback_failure_cannot_escape_native_window_callback(self):
        tray = sll_tray.TrayIcon(Mock(side_effect=RuntimeError("UI stopped")), Mock(), Mock(), Mock())
        with self.assertLogs(sll_tray.LOG, level="ERROR"):
            result = tray._window_proc(123, sll_tray.WM_TRAY, 0, sll_tray.NIN_SELECT)
        self.assertEqual(result, 0)

    def test_explorer_restart_readds_icon(self):
        tray = sll_tray.TrayIcon(Mock(), Mock(), Mock(), Mock())
        tray._taskbar_created = 9876
        tray._notify = Mock(return_value=True)
        tray._window_proc(123, 9876, 0, 0)
        tray._notify.assert_called_once_with(sll_tray.NIM_ADD)

    def test_power_broadcast_delivers_only_suspend_and_resume_events(self):
        event = Mock()
        tray = sll_tray.TrayIcon(Mock(), Mock(), Mock(), Mock(), on_system_event=event)
        for state in (sll_tray.PBT_APMSUSPEND, sll_tray.PBT_APMRESUMEAUTOMATIC,
                      sll_tray.PBT_APMRESUMESUSPEND, 10):
            self.assertEqual(tray._window_proc(123, sll_tray.WM_POWERBROADCAST, state, 0), 1)
        self.assertEqual(event.call_args_list, [unittest.mock.call("suspend"),
                                               unittest.mock.call("resume"), unittest.mock.call("resume")])

    def test_stop_before_start_is_safe(self):
        tray = sll_tray.TrayIcon(Mock(), Mock(), Mock(), Mock())
        self.assertTrue(tray.stop())

    def test_nonwindows_fails_cleanly(self):
        tray = sll_tray.TrayIcon(Mock(), Mock(), Mock(), Mock())
        with patch.object(sll_tray.os, "name", "posix"):
            self.assertFalse(tray.start())
        self.assertIn("Windows only", tray.error)

    @unittest.skipUnless(os.name == "nt", "Windows ctypes signatures")
    def test_native_structures_and_pointer_return_signatures(self):
        # Loads system libraries only; creates no windows or notification icon.
        api = sll_tray._WinAPI()
        self.assertEqual(ctypes.sizeof(api.NOTIFYICONDATA), 976 if ctypes.sizeof(ctypes.c_void_p) == 8 else 956)
        self.assertEqual(ctypes.sizeof(api.WNDCLASS), 72 if ctypes.sizeof(ctypes.c_void_p) == 8 else 40)
        self.assertIs(api.user32.DefWindowProcW.restype, ctypes.c_ssize_t)
        self.assertEqual(len(api.user32.CreateWindowExW.argtypes), 12)


if __name__ == "__main__":
    unittest.main()
