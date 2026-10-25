"""Private desktop contract fixtures; no PBX, GUI, playback or machine settings."""
from datetime import datetime, timezone
import io
import json
import threading
import unittest
import urllib.error
from urllib.parse import parse_qs, urlparse
from unittest import mock

import sls_mass_notify as client
import sls_presentation as presentation
from sls_protocol import notification_expiry, profile_namespace, validate_payload, validate_id
from sls_speech import NotificationAudio
from sls_store import InboxFullError
from tests.test_sls_client_reliability import IsolatedClientTest, notification, authenticated, sse


def announcement(identifier, **fields):
    return notification(identifier, kind="announcement", severity="", priority="notice",
        created_at=datetime.now(timezone.utc).isoformat(), **fields)


def page(cursor, events=(), **fields):
    return dict(ok=True, last_event_id=cursor, events=list(events), has_more=False, **fields)


def capabilities(preferred="json_poll", available=False):
    # Documented PBX 0.1.8-beta polling-response fields.
    return {"preferred": preferred, "sse_available": available,
            "reason_code": "shared_php_fpm_pool" if not available else "bounded_stream_slots",
            "sse_protocol": 2, "payload_schema": 1}


class TransportNegotiationTests(IsolatedClientTest):
    def test_poll_to_sse_and_planned_renewal_deliver_both_arrivals(self):
        worker = self.worker()
        baseline = page("tail", transport_capabilities=capabilities("sse", True))
        first = (authenticated("tail") + sse("notification", announcement("during-handoff"), "during-handoff")
                 + sse("reconnect", {"ok": True}))
        second = authenticated("during-handoff") + sse("notification", announcement("after-renewal"), "after-renewal")
        with mock.patch.object(client, "fetch_endpoint", return_value=(baseline, "", client.time.time())), \
             mock.patch.object(client, "open_sse_response", side_effect=[io.BytesIO(first), io.BytesIO(second)]) as opened, \
             mock.patch.object(worker.stop_event, "wait", side_effect=[False, True]):
            worker.run()
        self.assertEqual([call.kwargs for call in opened.call_args_list],
                         [{"last_event_id": "tail"}, {"last_event_id": "during-handoff"}])
        self.assertEqual({row["event_id"] for row in self.instance.inbox.history()}, {"during-handoff", "after-renewal"})
        self.assertEqual(len(self.instance.inbox.pending_receipts(self.namespace)), 2)

    def test_unchanged_poll_keeps_displayed_notification_and_pending_receipt(self):
        self.instance.accept_alert(0, self.alert())
        record = self.instance.inbox.history()[0]
        self.instance.alert_displayed(record["record_id"])
        worker = self.worker()
        replies = [page("tail", transport_capabilities=capabilities()), page("tail", unchanged=True)]
        with mock.patch.object(client, "fetch_endpoint", side_effect=[(p, "", client.time.time()) for p in replies]), \
             mock.patch.object(worker.stop_event, "wait", side_effect=[False, True]):
            worker.run()
        self.assertEqual(self.instance.inbox.record(record["record_id"])["state"], "displayed")
        self.assertEqual(len(self.instance.inbox.pending_receipts(self.namespace)), 1)

    def test_fpm_starts_in_polling_and_unchanged_response_retains_its_capability(self):
        worker = self.worker()
        replies = [page("@sls:empty", transport_capabilities=capabilities(), poll_interval_seconds=5),
                   page("new", [announcement("new")]), page("new", unchanged=True)]
        with mock.patch.object(client, "fetch_endpoint", side_effect=[(p, "", client.time.time()) for p in replies]) as fetch, \
             mock.patch.object(worker.stop_event, "wait", side_effect=[False, False, True]), \
             mock.patch.object(client, "open_sse_response") as stream:
            worker.run()
        stream.assert_not_called()
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(worker.preferred_transport, "json_poll")
        self.assertEqual([row["event_id"] for row in self.instance.inbox.history()], ["new"])
        self.assertEqual(self.instance.transport_statuses[0][0], "POLLING")

    def test_sse_preference_continues_the_authenticated_poll_baseline(self):
        worker = self.worker()
        reply = page("negotiated-tail", transport_capabilities=capabilities("sse", True))
        with mock.patch.object(client, "fetch_endpoint", return_value=(reply, "", client.time.time())) as fetch, \
             mock.patch.object(worker, "_run_live") as stream:
            worker.run()
        stream.assert_called_once_with(initial_cursor="negotiated-tail")
        query = parse_qs(urlparse(fetch.call_args.args[0]).query, keep_blank_values=True)
        self.assertEqual(query["last_event_id"], [""])
        self.assertFalse(self.instance.inbox.history())

    def test_unavailable_or_unsupported_sse_stays_on_healthy_polling(self):
        variants = [capabilities("sse", False), dict(capabilities("sse", True), sse_protocol=3)]
        for caps in variants:
            worker = self.worker()
            with mock.patch.object(client, "fetch_endpoint", return_value=(page("@sls:empty", transport_capabilities=caps), "", client.time.time())), \
                 mock.patch.object(worker.stop_event, "wait", return_value=True), \
                 mock.patch.object(worker, "_run_live") as stream:
                worker.run()
            stream.assert_not_called()
            self.assertEqual(self.instance.transport_statuses[0][0], "POLLING")

    def test_active_stream_retry_delay_prevents_a_new_sse_attempt(self):
        worker = self.worker()
        worker.endpoint_cfg["live_polling_until"] = client.time.time() + 300
        reply = page("@sls:empty", transport_capabilities=capabilities("sse", True))
        with mock.patch.object(client, "fetch_endpoint", return_value=(reply, "", client.time.time())), \
             mock.patch.object(worker.stop_event, "wait", return_value=True), \
             mock.patch.object(worker, "_run_live") as stream:
            worker.run()
        stream.assert_not_called()

    def test_poll_interval_is_used_and_pages_are_still_drained_without_wait(self):
        worker = self.worker()
        reply = page("@sls:empty", transport_capabilities=capabilities(), poll_interval_seconds=7)
        with mock.patch.object(client, "fetch_endpoint", return_value=(reply, "", client.time.time())), \
             mock.patch.object(worker.stop_event, "wait", return_value=True) as wait:
            worker.run()
        wait.assert_called_once_with(7.0)

    def test_connection_test_accepts_fpm_without_opening_a_stream(self):
        self.instance.connection_test_event = threading.Event()
        reply = page("@sls:empty", transport_capabilities=capabilities())
        with mock.patch.object(client, "fetch_endpoint", return_value=(reply, "", client.time.time())), \
             mock.patch.object(client, "open_sse_response") as stream:
            self.instance.test_now(lambda _message: None)
            while True:
                kind, value = self.instance.ui_queue.get(timeout=3)
                if kind == "test_result":
                    self.assertIn("Connection verified: 1/1", value[1])
                    break
        stream.assert_not_called()

    def test_connection_test_accepts_legacy_stream_capacity_fallback(self):
        self.instance.connection_test_event = threading.Event()
        with mock.patch.object(client, "fetch_endpoint", return_value=(page("@sls:empty"), "", client.time.time())), \
             mock.patch.object(client, "open_sse_response", side_effect=client.StreamCapacityError("FPM capacity", 300)):
            self.instance.test_now(lambda _message: None)
            while True:
                kind, value = self.instance.ui_queue.get(timeout=3)
                if kind == "test_result":
                    self.assertIn("Connection verified: 1/1", value[1])
                    break


class CursorPollingTests(IsolatedClientTest):
    def test_oversized_live_pages_reduce_limit_without_losing_cursor_or_notification(self):
        replies = [page("live-tail"), *[client.ResponseTooLargeError("bounded response") for _ in range(3)],
                   page("accepted", [announcement("accepted")])]
        with mock.patch.object(client, "pbx_recent_url", wraps=client.pbx_recent_url) as urls:
            _worker, wait = self.poll(replies, [False, True],
                                     ["", "live-tail", "live-tail", "live-tail", "live-tail"])
        self.assertEqual([call.kwargs["limit"] for call in urls.call_args_list], [100, 100, 25, 6, 1])
        self.assertEqual(wait.call_args_list, [mock.call(5.0), mock.call(5.0)])
        self.assertEqual([row["event_id"] for row in self.instance.inbox.history()], ["accepted"])

    def test_oversized_single_event_page_stops_bounded_retries(self):
        replies = [page("live-tail"), *[client.ResponseTooLargeError("bounded response") for _ in range(4)]]
        with mock.patch.object(client, "pbx_recent_url", wraps=client.pbx_recent_url) as urls:
            self.poll(replies, [False, True], ["", "live-tail", "live-tail", "live-tail", "live-tail"])
        self.assertEqual([call.kwargs["limit"] for call in urls.call_args_list], [100, 100, 25, 6, 1])
        self.assertEqual(self.instance.transport_statuses[0][0], "RECONNECTING")
        self.assertEqual(self.instance.inbox.history(), [])

    def poll(self, replies, waits, expected_cursors=None):
        worker = self.worker()
        requests = []
        iterator = iter(replies)
        def fetch(url, *_args, **_kwargs):
            requests.append(parse_qs(urlparse(url).query, keep_blank_values=True)["last_event_id"][0])
            result = next(iterator)
            if callable(result):
                result = result(worker)
            if isinstance(result, Exception):
                raise result
            return result, "", client.time.time()
        with mock.patch.object(client, "fetch_endpoint", side_effect=fetch), \
             mock.patch.object(worker.stop_event, "wait", side_effect=waits) as wait:
            worker._run_live_polling()
        if expected_cursors is not None:
            self.assertEqual(requests, expected_cursors)
        return worker, wait

    def test_burst_drains_all_pages_before_waiting_and_empty_response_preserves_popup(self):
        first = [announcement(f"burst-{i}") for i in range(100)]
        second = [announcement("https://example.test/opaque?id=a&b=%2F"), announcement("burst-101")]
        full = page("opaque/next?&", first)
        full["has_more"] = True
        unchanged = page("tail", unchanged=True)
        unchanged["latest"] = announcement("must-not-replay")
        worker, wait = self.poll([page("@sls:empty"), full, page("tail", second), unchanged],
                                [False, False, True], ["", "@sls:empty", "opaque/next?&", "tail"])
        self.assertEqual(wait.call_args_list, [mock.call(5.0)] * 3)
        self.assertEqual(len(self.instance.inbox.history()), 102)
        self.assertEqual(len(self.instance.inbox.pending_receipts(self.namespace, limit=256)), 102)
        self.assertEqual(self.instance.transport_statuses[0][0], "POLLING")
        self.instance.pump_inbox()
        self.instance.presenter.submit.assert_called()

    def test_outage_uses_explicit_empty_baseline_and_skips_missed_messages(self):
        self.poll([page("old"), OSError("offline"), page("missed", [announcement("missed")]),
                   page("fresh", [announcement("fresh")])], [False, False, False, True], ["", "old", "", "missed"])
        self.assertEqual([r["event_id"] for r in self.instance.inbox.history()], ["fresh"])

    def test_cursor_gap_discards_retained_records(self):
        gap = page("new-baseline", [announcement("retained")], cursor_gap=True)
        self.poll([page("old"), gap, page("new", [announcement("new")])],
                  [False, False, True], ["", "old", "new-baseline"])
        self.assertEqual([r["event_id"] for r in self.instance.inbox.history()], ["new"])

    def test_nonadvancing_page_fails_without_looping_or_advancing_receipts(self):
        broken = page("tail", [announcement("bad")]); broken["has_more"] = True
        self.poll([page("tail"), broken], [False, True])
        self.assertEqual(self.instance.inbox.history(), [])
        self.assertEqual(self.instance.transport_statuses[0][0], "RECONNECTING")

    def test_obsolete_poll_200_or_401_cannot_change_new_account(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                self.instance.config["endpoints"][0] = dict(self.profile)
                def late(_worker):
                    self.instance.config["endpoints"][0]["password"] = "replacement password"
                    self.instance.transport_statuses[0] = ("POLLING", "new connection")
                    return client.UnauthorizedError("old password") if failure else page("obsolete", [announcement("obsolete")])
                self.poll([late], [], [""])
                self.assertEqual(self.instance.transport_statuses[0], ("POLLING", "new connection"))
                self.assertEqual(self.instance.inbox.history(), [])

    def test_inflight_poll_cannot_restart_a_worker_revoked_by_receipts(self):
        def late(worker):
            worker._invalidate_auth(revoked=True)
            return page("obsolete", [announcement("obsolete")])
        worker, wait = self.poll([late], [True], [""])
        wait.assert_called_once_with()  # Remain parked until credentials change.
        self.assertTrue(worker.revoked_event.is_set())
        self.assertEqual(self.instance.transport_statuses[0][0], "AUTH_FAILED")
        self.assertEqual(self.instance.inbox.history(), [])

    def test_replaced_enrollment_does_not_inherit_dedup_or_receipts(self):
        worker = self.worker()
        self.assertTrue(worker._bind_desktop_identity("enrollment-one"))
        old = profile_namespace(worker.endpoint_cfg)
        worker._accept_payload(announcement("same-event"), "")
        worker.endpoint_cfg["live_polling_until"] = client.time.time() + 300
        self.assertTrue(worker._bind_desktop_identity("enrollment-two"))
        new = profile_namespace(worker.endpoint_cfg)
        self.assertNotEqual(old, new)
        self.assertEqual(worker.endpoint_cfg["live_polling_until"], 0)
        self.assertIsNone(worker.preferred_transport)
        self.assertEqual(self.instance.inbox.pending_receipts(new), [])
        self.assertTrue(worker._accept_payload(announcement("same-event"), ""))
        self.assertEqual(len(self.instance.inbox.history()), 2)
        self.assertEqual(len(self.instance.inbox.pending_receipts(old)), 1)
        self.assertEqual(len(self.instance.inbox.pending_receipts(new)), 1)

    def test_saving_the_same_account_retains_server_enrollment_binding_and_preferences(self):
        original = dict(self.instance.config["endpoints"][0])
        candidate = dict(original)
        candidate.pop("desktop_client_id")  # The actual Settings form omits this runtime field.
        with mock.patch.object(client, "save_config"):
            self.instance.update_settings(endpoints=[candidate], enabled=True,
                startup_enabled=False, auto_update_enabled=False, audio_sound=client.DEFAULT_AUDIO_NAME)
        saved = self.instance.config["endpoints"][0]
        self.assertEqual(saved["desktop_client_id"], original["desktop_client_id"])
        self.assertEqual(profile_namespace(saved), self.namespace)
        self.assertEqual(saved["password"], original["password"])


class ReceiptCompatibilityTests(IsolatedClientTest):
    def test_legacy_timeout_without_publication_time_is_frozen_on_first_receipt(self):
        alert = self.alert(kind="announcement", display_timeout_seconds=30)
        now = client.time.time()
        self.instance.accept_alert(0, alert)
        saved = self.instance.inbox.history()[0]
        self.assertAlmostEqual(saved["expires"], now + 30, delta=1)
        self.instance.accept_alert(0, self.alert(kind="announcement", display_timeout_seconds=30))
        self.assertEqual(self.instance.inbox.record(saved["record_id"])["expires"], saved["expires"])

    def test_unicode_receipt_stays_within_request_limit_and_accepts_escaped_confirmation(self):
        identifier = "é" * 1024
        body = json.dumps({"ok": True, "event_id": identifier}).encode("utf-8")
        self.assertGreater(len(body), 4096)
        with mock.patch.object(client, "open_http_request", return_value=io.BytesIO(body)) as opened:
            client.send_receipt_ack(self.profile, identifier)
        request = opened.call_args.args[0]
        self.assertLessEqual(len(request.data), 4096)
        self.assertEqual(json.loads(request.data)["event_id"], identifier)

    def receipt_worker(self):
        worker = self.worker()
        self.instance.accept_alert(0, self.alert())
        worker.authenticated_event.set()
        return worker, self.instance.inbox.pending_receipts(self.namespace)[0]

    def test_retryable_503_keeps_exact_event_and_server_delay(self):
        worker, receipt = self.receipt_worker()
        now = client.time.time()
        with mock.patch.object(client, "send_receipt_ack", side_effect=client.ServiceUnavailableError("busy", 300)), \
             mock.patch.object(worker.stop_event, "wait", return_value=True):
            worker._run_receipts()
        row = self.instance.inbox.db.execute("SELECT * FROM receipt_outbox WHERE receipt_id=?", (receipt["receipt_id"],)).fetchone()
        self.assertEqual(row["event_id"], "event-1")
        self.assertIsNone(row["sent"])
        self.assertGreaterEqual(row["retry_after"], now + 300)

    def test_late_ack_success_or_401_cannot_remove_receipt_or_revoke_new_session(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                worker, receipt = self.receipt_worker()
                def late(*_args):
                    self.instance.config["endpoints"][0]["credential_revision"] += 1
                    self.instance.transport_statuses[0] = ("POLLING", "new session")
                    if failure:
                        raise client.UnauthorizedError("obsolete")
                with mock.patch.object(client, "send_receipt_ack", side_effect=late), \
                     mock.patch.object(worker.stop_event, "wait", return_value=True):
                    worker._run_receipts()
                row = self.instance.inbox.db.execute("SELECT * FROM receipt_outbox WHERE receipt_id=?", (receipt["receipt_id"],)).fetchone()
                self.assertIsNone(row["sent"])
                self.assertEqual(row["attempts"], 0)
                self.assertFalse(worker.revoked_event.is_set())
                self.assertEqual(self.instance.transport_statuses[0], ("POLLING", "new session"))

    def test_terminal_event_rejection_is_retained_without_endless_retries(self):
        worker, receipt = self.receipt_worker()
        with mock.patch.object(client, "send_receipt_ack", side_effect=client.ReceiptRejectedError("no longer authorized")), \
             mock.patch.object(worker.stop_event, "wait", return_value=True):
            worker._run_receipts()
        self.assertEqual(self.instance.inbox.pending_receipts(self.namespace), [])
        row = self.instance.inbox.db.execute("SELECT terminal,sent FROM receipt_outbox WHERE receipt_id=?", (receipt["receipt_id"],)).fetchone()
        self.assertEqual(row["terminal"], 1)
        self.assertIsNone(row["sent"])
        self.assertIn("receipt-rejected-0", self.instance.faults)

    def test_pending_receipts_are_bounded_independently_of_dismissed_history(self):
        self.instance.inbox.max_pending = 1
        self.instance.accept_alert(0, self.alert("first"))
        self.instance.inbox.mark(self.instance.inbox.history()[0]["record_id"], "dismissed")
        with self.assertRaises(InboxFullError):
            self.instance.accept_alert(0, self.alert("second"))
        self.assertEqual(len(self.instance.inbox.pending_receipts(self.namespace)), 1)

    def test_missing_published_event_id_is_quarantined_without_fabricated_receipt(self):
        payload = announcement("placeholder")
        payload.pop("id")
        self.assertFalse(self.worker()._accept_payload(payload, json.dumps(payload)))
        self.assertEqual(self.instance.inbox.pending_receipts(self.namespace), [])
        self.assertEqual(len(self.instance.inbox.quarantined()), 1)

    def test_400_unknown_event_is_retained_as_terminal_not_acknowledged(self):
        error = urllib.error.HTTPError("https://pbx.example.test/api/sipnotify/desktop/ack", 400,
            "Bad request", {}, io.BytesIO(b'{"ok":false,"error":"unknown_or_unauthorized_event"}'))
        with mock.patch.object(client, "open_http_request", side_effect=error):
            with self.assertRaises(client.ReceiptRejectedError):
                client.send_receipt_ack(self.profile, "unknown-event")
        self.assertTrue(error.closed)


class StreamRenewalTests(IsolatedClientTest):
    def test_failed_initial_handoff_drops_its_cursor_before_retrying(self):
        worker = self.worker()
        with mock.patch.object(client, "open_sse_response", side_effect=[OSError("offline"), io.BytesIO(authenticated())]) as opened, \
             mock.patch.object(worker.stop_event, "wait", side_effect=[False, True]):
            worker._run_live(initial_cursor="initial-live-tail")
        self.assertEqual(opened.call_args_list[0].kwargs, {"last_event_id": "initial-live-tail"})
        self.assertEqual(opened.call_args_list[1].kwargs, {})

    def test_unicode_sse_cursor_uses_the_original_utf8_header_bytes(self):
        identifier = "urn:weather:区域/é"
        response = io.BytesIO(); response.headers = {"Content-Type": "text/event-stream"}
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(client, "build_http_opener", return_value=opener):
            client.open_sse_response(self.profile, last_event_id=identifier)
        header = opener.open.call_args.args[0].get_header("Last-event-id")
        self.assertEqual(header.encode("latin-1"), identifier.encode("utf-8"))
        self.assertEqual(parse_qs(urlparse(client.pbx_recent_url(self.profile, identifier)).query)["last_event_id"], [identifier])

    def test_planned_renewal_continues_cursor_but_reset_and_disconnect_do_not(self):
        for control, continuation in (("reconnect", True), ("cursor_reset", False), (None, False)):
            with self.subTest(control=control):
                worker = self.worker()
                first = authenticated("baseline") + sse("notification", announcement("one"), "one")
                if control:
                    first += sse(control, {"ok": True})
                second = authenticated("one") + sse("notification", announcement("two"), "two")
                with mock.patch.object(client, "open_sse_response", side_effect=[io.BytesIO(first), io.BytesIO(second)]) as opened, \
                     mock.patch.object(worker.stop_event, "wait", side_effect=[False, True]):
                    worker._run_live()
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(opened.call_args.kwargs, {"last_event_id": "one"} if continuation else {})

    def test_only_explicit_healthy_continuation_sets_last_event_id(self):
        response = io.BytesIO(); response.headers = {"Content-Type": "text/event-stream"}
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(client, "build_http_opener", return_value=opener):
            client.open_sse_response(self.profile, last_event_id="opaque?x=&y")
        self.assertEqual(opener.open.call_args.args[0].get_header("Last-event-id"), "opaque?x=&y")


class ContentCompatibilityTests(unittest.TestCase):
    def test_event_id_limits_use_utf8_bytes_and_preserve_opaque_content(self):
        for identifier in ("a" * 2048, "é" * 1024, "urn:weather:区域/one", "opaque internal space"):
            self.assertEqual(validate_id(identifier), identifier)
            self.assertEqual(validate_payload(announcement(identifier))["id"], identifier)
        for identifier in ("a" * 2049, "é" * 1025, "é" * 1000 + "区域" * 9, "bad\r\nHeader: value", "bad\x00id", "\ud800"):
            with self.subTest(length=len(identifier)), self.assertRaises(ValueError):
                validate_id(identifier)

    def test_long_display_timeout_is_accepted_but_cannot_extend_ten_minute_cap(self):
        data = announcement("long-timeout", display_timeout_seconds=10**100)
        validate_payload(data)
        start = client.timestamp(data["created_at"])
        self.assertEqual(notification_expiry(data), start + 600)

    def test_legacy_bare_hostnames_keep_distinct_normalized_origins_and_ports(self):
        first = dict(endpoint="pbx.example.test:8443", username="desktop")
        self.assertEqual(profile_namespace(first), profile_namespace(dict(first, endpoint="https://PBX.example.test:8443")))
        self.assertNotEqual(profile_namespace(first), profile_namespace(dict(first, endpoint="other.example.test:8443")))
        self.assertNotEqual(profile_namespace(first), profile_namespace(dict(first, endpoint="pbx.example.test")))

    def test_nullable_expiry_and_earliest_deadline_are_shared(self):
        published = "2026-10-24T10:00:00Z"
        start = datetime(2026, 10, 24, 10, tzinfo=timezone.utc).timestamp()
        for timeout in (None, 0, 86400):
            for optional in (None, ""):
                data = announcement("expiry", display_timeout_seconds=timeout, display_expires_at=optional)
                data["created_at"] = published
                validate_payload(data)
                self.assertEqual(notification_expiry(data), start + 600)
                alert = client.extract_alert(data, "")
                self.assertEqual(client.alert_expiry(alert), start + 600)
                self.assertEqual(presentation.presentation_policy(alert).expires.timestamp(), start + 600)
        data["display_timeout_seconds"] = 30
        self.assertEqual(notification_expiry(data), start + 30)
        data["display_expires_at"] = "2026-10-24T10:00:10Z"
        self.assertEqual(notification_expiry(data), start + 10)

    def test_explicit_live_boolean_overrides_legacy_test_metadata(self):
        data = announcement("test", is_test=False, test_only=True, status="exercise")
        data["severity"] = "Test"
        alert = client.extract_alert(validate_payload(data), "")
        self.assertFalse(alert.test_only)
        self.assertIs(presentation.explicit_test_mode(alert), False)

    def test_weather_details_preserve_separate_body_description_and_instructions(self):
        data = notification("weather", message="Headline", description="Full NWS description",
                            instructions="Use the interior shelter", message_type="Update", beep="no")
        alert = client.extract_alert(validate_payload(data), "")
        self.assertEqual((alert.body, alert.description, alert.instructions, alert.message_type),
                         ("Headline", "Full NWS description", "Use the interior shelter", "Update"))
        self.assertFalse(alert.beep)

    def test_audio_retains_speech_but_suppresses_beep_and_uses_monotonic_expiry(self):
        audio = NotificationAudio.__new__(NotificationAudio)
        audio._condition = threading.Condition(); audio._closed = False
        audio._completed = set(); audio._pending = []; audio._active = None
        with mock.patch("sls_speech.time.time", return_value=100), mock.patch("sls_speech.time.monotonic", return_value=50):
            audio.submit("silent-chime", {"kind": "announcement", "body": "Read this", "beep": False}, 3, 110)
        job = audio._pending[0]
        self.assertFalse(job.tone_enabled)
        with mock.patch("sls_speech.time.time", return_value=20), mock.patch("sls_speech.time.monotonic", return_value=61):
            self.assertFalse(audio._valid(job))

    def test_retry_after_http_date_and_nonfinite_values(self):
        self.assertEqual(client.retry_after_seconds("Sat, 24 Oct 2026 10:05:00 GMT",
            now=datetime(2026, 10, 24, 10, tzinfo=timezone.utc).timestamp()), 300)
        self.assertEqual(client.retry_after_seconds("NaN"), 60)
        self.assertEqual(client.retry_after_seconds("7200"), 7200)


class MediaCompatibilityTests(IsolatedClientTest):
    def setUp(self):
        super().setUp()
        self.profile.update(endpoint="https://pbx.example.test:8443", authenticated_images_enabled=True)
        self.url = self.profile["endpoint"] + "/api/sipnotify/desktop/media?event_id=one"

    def test_compatibility_image_never_sends_basic_credentials(self):
        with mock.patch.object(client, "open_http_request", return_value=io.BytesIO(b"image")) as opened:
            client.fetch_image_bytes(self.profile["endpoint"] + "/generated/image.png", source_endpoint=self.profile["endpoint"])
        self.assertIsNone(opened.call_args.args[0].get_header("Authorization"))

    def test_opted_in_exact_event_media_uses_its_own_account(self):
        with mock.patch.object(client, "open_http_request", return_value=io.BytesIO(b"image")) as opened:
            client.fetch_image_bytes(self.url, source_endpoint=self.profile["endpoint"], endpoint_cfg=self.profile,
                                     event_id="one", image_authentication="desktop_basic")
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, self.url)
        self.assertEqual(request.get_header("Authorization"), client.endpoint_auth_headers(self.profile)["Authorization"])
        self.assertEqual(request.get_header("X-sls-client-version"), "1.0.13-beta")

    def test_disabled_cross_origin_arbitrary_path_and_other_event_are_blocked(self):
        for url, enabled in ((self.url, False), (self.url.replace(":8443", ""), True),
                             (self.url.replace("/media", "/other"), True), (self.url + "&event_id=two", True),
                             (self.url.replace("event_id=one", "event_id=two"), True)):
            with self.subTest(url=url, enabled=enabled), mock.patch.object(client, "open_http_request") as opened:
                with self.assertRaises(client.ApiError):
                    client.fetch_image_bytes(url, source_endpoint=self.profile["endpoint"],
                        endpoint_cfg=dict(self.profile, authenticated_images_enabled=enabled),
                        event_id="one", image_authentication="desktop_basic")
                opened.assert_not_called()

    def test_same_host_accounts_are_selected_by_namespace(self):
        other = dict(self.profile, username="other-desktop", password="other secret")
        self.instance.config["endpoints"] = [self.profile, other]
        alert = client.extract_alert(announcement("one", image_url=self.url, image_authentication="desktop_basic"), "")
        alert.source_endpoint = self.profile["endpoint"]
        alert.source_namespace = profile_namespace(other)
        with mock.patch.object(client, "fetch_image_bytes", return_value=b"image") as fetch:
            self.instance.load_alert_image(alert)
        self.assertEqual(fetch.call_args.kwargs["endpoint_cfg"]["username"], "other-desktop")

    def test_authenticated_media_redirect_to_another_path_is_blocked(self):
        request = urllib.request.Request(self.url, headers={"Authorization": "Basic fixture"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            client.SameOriginRedirectHandler().redirect_request(request, None, 302, "redirect", {}, self.url.replace("/media", "/other"))
        caught.exception.close()

    def test_image_larger_than_five_mib_is_rejected(self):
        with mock.patch.object(client, "open_http_request", return_value=io.BytesIO(b"x" * (5 * 1024 * 1024 + 1))):
            with self.assertRaises(client.ApiError):
                client.fetch_image_bytes(self.profile["endpoint"] + "/large.png")
