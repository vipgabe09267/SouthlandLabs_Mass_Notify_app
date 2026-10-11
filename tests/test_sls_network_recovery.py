"""Wake recovery and fault delivery regressions without a real PBX or NIC."""
from unittest import mock

import sls_mass_notify as client
from tests.test_sls_client_reliability import IsolatedClientTest


class NetworkRecoveryTests(IsolatedClientTest):
    def drain(self):
        events = []
        while not self.instance.ui_queue.empty():
            events.append(self.instance.ui_queue.get_nowait())
        return events

    def test_wake_discards_aged_and_queued_transient_faults_but_preserves_auth_fault(self):
        with mock.patch.object(client.time, "monotonic", return_value=100):
            self.instance.record_fault("endpoint-0", "Disconnected", recoverable=True)
            self.instance.record_fault("endpoint-1", "Credentials revoked")
        with mock.patch.object(client.time, "monotonic", return_value=1000):
            self.instance.evaluate_faults()
            self.instance.begin_network_recovery()
        self.assertNotIn("endpoint-0", self.instance.faults)
        self.assertIn("endpoint-1", self.instance.faults)
        self.assertEqual(self.instance._network_recovery_until, 1090)
        self.instance.root = mock.Mock()
        self.instance.settings_window = None
        self.instance.tray = mock.Mock()
        self.instance.stop_event.set()
        with mock.patch.object(client, "FaultToast") as toast:
            self.instance.process_ui_queue()
        toast.assert_called_once_with(self.instance, "Credentials revoked")

    def test_nic_restoration_and_receipt_retry_are_quiet_during_grace(self):
        with mock.patch.object(client.time, "monotonic", return_value=100):
            self.instance.begin_network_recovery()
            self.assertFalse(self.instance.record_fault("endpoint-0", "NIC unavailable", recoverable=True))
            self.assertFalse(self.instance.record_fault("receipt-0", "Receipt retry", recoverable=True))
            self.instance.evaluate_faults()
        self.assertEqual(self.instance.faults, {})
        self.assertFalse(any(kind == "fault" for kind, _ in self.drain()))

    def test_continuous_outage_warns_once_after_grace_and_threshold(self):
        self.instance._network_recovery_until = 190
        with mock.patch.object(client.time, "monotonic", return_value=191):
            self.assertTrue(self.instance.record_fault("endpoint-0", "Disconnected", recoverable=True))
        with mock.patch.object(client.time, "monotonic", return_value=490):
            self.instance.evaluate_faults()
        self.assertFalse(any(kind == "fault" for kind, _ in self.drain()))
        with mock.patch.object(client.time, "monotonic", return_value=491):
            self.instance.record_fault("endpoint-0", "Still disconnected", recoverable=True)
            self.instance.evaluate_faults()
            self.instance.evaluate_faults()
        self.assertEqual(len([event for event in self.drain() if event[0] == "fault"]), 1)

    def test_resolved_fault_does_not_display_and_closes_visible_notice(self):
        with mock.patch.object(client.time, "monotonic", return_value=100):
            self.instance.record_fault("endpoint-0", "Disconnected", recoverable=True)
        fault = self.instance.faults["endpoint-0"]
        self.instance.fault_toast = mock.Mock(fault_key="endpoint-0", fault_token=fault["token"])
        visible = self.instance.fault_toast
        with mock.patch.object(client.time, "monotonic", return_value=500):
            self.instance.evaluate_faults()
        self.instance.clear_fault("endpoint-0")
        self.instance.root = mock.Mock()
        self.instance.settings_window = None
        self.instance.tray = mock.Mock()
        self.instance.stop_event.set()
        with mock.patch.object(client, "FaultToast") as toast:
            self.instance.process_ui_queue()
        toast.assert_not_called()
        visible.hide.assert_called_once()

    def test_credentials_fault_is_not_hidden_during_network_recovery(self):
        with mock.patch.object(client.time, "monotonic", return_value=100):
            self.instance.begin_network_recovery()
            self.instance.record_fault("endpoint-0", "Credentials revoked")
        self.assertFalse(self.instance.faults["endpoint-0"]["recoverable"])

    def test_replaced_fault_cannot_display_an_old_notice(self):
        self.instance.record_fault("endpoint-0", "Disconnected", recoverable=True)
        old_token = self.instance.faults["endpoint-0"]["token"]
        self.instance.record_fault("endpoint-0", "Credentials revoked")
        self.assertNotEqual(old_token, self.instance.faults["endpoint-0"]["token"])
        self.assertFalse(self.instance.faults["endpoint-0"]["recoverable"])
