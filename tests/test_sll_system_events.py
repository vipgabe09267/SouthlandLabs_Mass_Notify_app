"""Native lifecycle behavior and address subscription; no windows or network traffic."""
import ctypes
import os
import unittest
from unittest import mock

from sll_system_events import AddressChangeSubscription, RecoverySignals
from tests.test_sll_client_reliability import IsolatedClientTest, notification


class SignalTests(unittest.TestCase):
    def test_suspend_fences_until_resume_is_processed(self):
        signals = RecoverySignals()
        signals.signal("suspend")
        generation, kind, suspended = signals.snapshot()
        self.assertEqual(kind, "suspend")
        self.assertTrue(suspended)
        signals.complete(generation)
        self.assertTrue(signals.blocked)
        signals.signal("resume")
        generation, kind, suspended = signals.snapshot()
        self.assertEqual(kind, "resume")
        self.assertFalse(suspended)
        self.assertTrue(signals.blocked)
        signals.complete(generation)
        self.assertFalse(signals.blocked)

    def test_address_burst_and_duplicate_resume_are_coalesced(self):
        signals = RecoverySignals()
        with mock.patch("sll_system_events.time.monotonic", return_value=100):
            signals.signal("network")
            generation = signals.snapshot()[0]
            signals.signal("network")
            self.assertEqual(signals.snapshot()[0], generation)
            signals.signal("resume")
            generation = signals.snapshot()[0]
            signals.signal("resume")
            signals.signal("network")
            self.assertEqual(signals.snapshot()[0], generation)

    def test_completing_old_event_cannot_clear_new_signal(self):
        signals = RecoverySignals()
        signals.signal("network")
        old_generation = signals.snapshot()[0]
        signals.signal("suspend")
        signals.complete(old_generation)
        self.assertEqual(signals.snapshot()[1], "suspend")
        self.assertTrue(signals.blocked)

    def test_callback_filters_initial_and_parameter_updates_and_closes_safely(self):
        callback = mock.Mock()
        subscription = AddressChangeSubscription(callback)
        for kind in (0, 3):
            subscription._changed(None, None, kind)
        callback.assert_not_called()
        for kind in (1, 2):
            subscription._changed(None, None, kind)
        self.assertEqual(callback.call_count, 2)
        subscription.close()
        subscription._changed(None, None, 1)
        self.assertEqual(callback.call_count, 2)

    def test_callback_errors_cannot_escape_native_boundary(self):
        subscription = AddressChangeSubscription(mock.Mock(side_effect=ValueError("closed")))
        with self.assertLogs("sll_system_events", "ERROR"):
            subscription._changed(None, None, 1)

    @unittest.skipUnless(os.name == "nt", "Windows IP Helper")
    def test_native_subscription_registers_and_cancels_without_any_window(self):
        callback = mock.Mock()
        subscription = AddressChangeSubscription(callback)
        try:
            subscription.start()
            self.assertTrue(subscription._handle.value)
            self.assertIs(subscription._api.NotifyUnicastIpAddressChange.restype, ctypes.wintypes.ULONG)
        finally:
            subscription.close()
        self.assertIsNone(subscription._native_callback)
        self.assertFalse(subscription._handle.value)


class RecoveryIntegrationTests(IsolatedClientTest):
    def setUp(self):
        super().setUp()
        self.instance.system_signals = RecoverySignals()

    def test_short_suspend_is_detected_without_waiting_for_elapsed_time(self):
        self.instance._last_delivery_tick = __import__("time").time()
        worker = self.worker()
        self.instance.accept_alert(0, self.alert("before"))
        self.instance.system_signals.signal("suspend")
        self.assertFalse(worker._accept_payload(notification("buffered"), "", "buffered"))
        self.instance.check_delivery_resume()
        self.assertEqual(self.instance.inbox.history()[0]["state"], "expired")
        self.assertTrue(worker.stop_event.is_set())
        self.assertTrue(self.instance.system_signals.blocked)
        self.instance.system_signals.signal("resume")
        self.instance.check_delivery_resume()
        self.assertFalse(self.instance.system_signals.blocked)
        fresh = self.worker()
        self.assertTrue(fresh._accept_payload(notification("fresh"), "", "fresh"))

    def test_network_change_retires_pending_queue_but_keeps_displayed_alert(self):
        worker = self.worker()
        self.instance.accept_alert(0, self.alert("visible"))
        record = self.instance.inbox.history()[0]
        self.instance.inbox.mark(record["record_id"], "displayed")
        self.instance.accept_alert(0, self.alert("waiting"))
        self.instance.system_signals.signal("network")
        self.instance.check_delivery_resume()
        states = {row["event_id"]: row["state"] for row in self.instance.inbox.history()}
        self.assertEqual(states, {"visible": "displayed", "waiting": "expired"})
        self.assertTrue(worker.stop_event.is_set())

    def test_network_change_cannot_reauthorize_revoked_credentials(self):
        worker = self.worker()
        worker._invalidate_auth(revoked=True)
        self.instance.system_signals.signal("network")
        self.instance.check_delivery_resume()
        self.assertIs(self.instance.workers[0], worker)
        self.assertTrue(worker.revoked_event.is_set())
