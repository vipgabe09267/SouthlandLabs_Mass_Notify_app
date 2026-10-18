"""Desktop self-response contract tests; no PBX requests, windows, or credentials."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sls_incidents import IncidentClient, response_incident, validate_projection
from sls_store import Inbox
import sls_mass_notify as client
from tests.test_sls_client_reliability import IsolatedClientTest, notification


IDENTIFIER = "inc_" + "a" * 32


def metadata(**changes):
    value = dict(schema=1, incident_id=IDENTIFIER, sequence=1, kind="initial",
                 severity="critical", is_test=True)
    value.update(changes)
    return value


def projection(**changes):
    value = dict(ok=True, success=True, schema=1, id=IDENTIFIER, title="Evacuation drill",
                 state="open", is_test=True, person={"desktop_username": "desktop-1"}, response=None)
    value.update(changes)
    return value


class IncidentContractTests(unittest.TestCase):
    def setUp(self):
        self.inbox = Inbox(":memory:")
        self.addCleanup(self.inbox.close)
        self.request = mock.Mock(return_value=projection())
        self.client = IncidentClient(self.request, self.inbox, "one", "desktop-1", IDENTIFIER)

    def test_only_explicit_supported_metadata_enables_controls(self):
        self.assertEqual(response_incident({"incident": metadata(), "is_test": True}), IDENTIFIER)
        for value in (metadata(schema=True), metadata(schema=2), metadata(sequence=True),
                      metadata(sequence=251), metadata(is_test="true"), metadata(kind="cancel"), metadata(kind=[]),
                      metadata(severity={}),
                      metadata(incident_id="../escape"), metadata(severity="unknown")):
            with self.subTest(value=value):
                self.assertEqual(response_incident({"incident": value, "is_test": True}), "")
        self.assertEqual(response_incident({"incident": metadata(), "is_test": False}), "")
        self.assertEqual(response_incident({"message": "I am safe, all clear", "incident_id": IDENTIFIER}), "")

    def test_details_use_the_recipient_endpoint_and_do_not_submit_a_response(self):
        details = self.client.details()
        self.request.assert_called_once_with("GET", "/api/sipnotify/desktop/incident?incident_id=" + IDENTIFIER, None)
        self.assertEqual(details["state"], "open")
        self.assertNotIn("person", details)
        self.assertIsNone(self.client.pending())

    def test_projection_rejects_other_identity_id_and_malformed_success(self):
        for changes in ({"person": {"desktop_username": "other"}}, {"id": "inc_" + "b" * 32},
                        {"ok": False}, {"success": 1}, {"schema": True}, {"state": "unknown"},
                        {"response": {"response": "evacuated"}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_projection(projection(**changes), IDENTIFIER, "desktop-1")

    def test_operator_missing_status_does_not_prevent_a_desktop_from_answering(self):
        self.request.return_value = projection(response={"response": "missing"})
        self.assertEqual(self.client.details()["response"], "missing")
        with self.assertRaises(ValueError):
            self.client.respond("missing")

    def test_explicit_response_posts_only_self_contract_fields_and_confirms(self):
        self.request.return_value = projection(response={"response": "safe"})
        self.client.respond("safe")
        method, path, body = self.request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/sipnotify/desktop/incident/respond"))
        self.assertEqual(set(body), {"incident_id", "request_id", "response"})
        self.assertRegex(body["request_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(body["response"], "safe")
        self.assertIsNone(self.client.pending())

    def test_ambiguous_retry_keeps_the_same_durable_request_id(self):
        attempts = []

        def request(method, path, body):
            attempts.append(copy.deepcopy(body))
            self.assertIsNotNone(self.client.pending())  # committed before POST
            if len(attempts) == 1:
                raise TimeoutError("reply lost after server accepted")
            return projection(response={"response": "needs_assistance"})

        self.client.request = request
        with self.assertRaises(TimeoutError):
            self.client.respond("needs_assistance")
        with self.assertRaisesRegex(ValueError, "saved unconfirmed"):
            self.client.respond("safe")
        self.client.respond("needs_assistance")
        self.assertEqual(attempts[0], attempts[1])
        self.assertIsNone(self.client.pending())

    def test_wrong_or_missing_confirmation_does_not_clear_saved_request(self):
        for value in (projection(response={"response": "received"}), projection(response=None),
                      projection(id="inc_" + "b" * 32, response={"response": "safe"})):
            self.request.return_value = value
            with self.assertRaises(ValueError):
                self.client.respond("safe")
            self.assertEqual(self.client.pending()["response"], "safe")

    def test_pending_request_survives_restart_is_scoped_and_never_changes_delivery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            store = Inbox(path)
            record, _ = store.receive("one", "event", {}, receipt_event_id="event")
            request = store.begin_human_response("one", IDENTIFIER, "received")
            store.close()
            store = Inbox(path)
            try:
                self.assertEqual(store.pending_human_response("one", IDENTIFIER), request)
                self.assertIsNone(store.pending_human_response("other", IDENTIFIER))
                self.assertEqual(store.record(record)["state"], "pending")
                self.assertEqual(len(store.pending_receipts("one")), 1)
                store.confirm_human_response(request["request_id"])
                self.assertEqual(store.record(record)["state"], "pending")
            finally:
                store.close()


class IncidentDeliveryTests(IsolatedClientTest):
    def test_incident_request_reports_version_and_uses_only_desktop_basic_credentials(self):
        self.instance.root = mock.Mock()
        payload = notification("incident", is_test=True, incident=metadata())
        self.worker()._accept_payload(payload, json.dumps(payload), "incident")
        record = self.instance.inbox.history()[0]
        with mock.patch.object(client, "IncidentResponseWindow") as window:
            self.instance.show_incident_response(record["record_id"])
        incident_client = window.call_args.args[1]
        with mock.patch.object(client, "open_http_request", return_value=io.BytesIO(json.dumps(projection()).encode())) as opened:
            incident_client.details()
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://pbx.example.test/api/sipnotify/desktop/incident?incident_id=" + IDENTIFIER)
        self.assertEqual(request.get_header("X-sls-client-version"), client.APP_VERSION)
        self.assertEqual(request.get_header("X-sls-payload-schema"), "1")
        self.assertEqual(request.get_header("X-sls-sse-protocol"), "2")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertTrue(opened.call_args.kwargs["same_origin"])

        # Retained dialogs cannot send after switching identity or rotating credentials.
        self.instance.config["endpoints"][0]["credential_revision"] += 1
        with mock.patch.object(client, "open_http_request") as opened:
            with self.assertRaises(client.UnauthorizedError):
                incident_client.respond("safe")
        opened.assert_not_called()

    def test_incident_metadata_is_preserved_without_turning_all_clear_into_popup_cancellation(self):
        payload = notification("all-clear", kind="announcement", is_test=True,
                               incident=metadata(kind="all_clear", sequence=2))
        worker = self.worker()
        self.assertTrue(worker._accept_payload(payload, json.dumps(payload), "all-clear"))
        record = self.instance.inbox.history()[0]
        self.assertEqual(record["payload"]["response_incident_id"], IDENTIFIER)
        self.assertEqual(record["payload"]["action"], "notify")
        self.assertEqual(record["incident_id"], "")
        self.assertEqual(record["state"], "pending")
        self.assertEqual(len(self.instance.inbox.pending_receipts(self.namespace)), 1)
        self.assertIsNone(self.instance.inbox.pending_human_response(self.namespace, IDENTIFIER))
