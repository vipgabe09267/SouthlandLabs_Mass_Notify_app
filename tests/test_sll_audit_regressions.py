"""Failure-path checks from the 1.0.13 audit; no GUI, PBX or audible output."""
from datetime import datetime, timezone
import copy
import hashlib
import io
import json
import queue
import socket
import sqlite3
import threading
import time
from pathlib import Path
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import sll_mass_notify as client
import sll_presentation as presentation
import sll_voices as voices
from tests.test_sll_client_reliability import IsolatedClientTest, notification, authenticated, sse
from tests.test_sll_incidents import metadata, projection
from tests.test_sll_transport_deadlines import SocketResponse


class DispatchRecoveryTests(IsolatedClientTest):
    def test_transient_resume_storage_failure_keeps_the_ui_pump_scheduled(self):
        self.instance.root = mock.Mock()
        self.instance.settings_window = None
        self.instance.tray = mock.Mock()
        with mock.patch.object(self.instance, "check_delivery_resume", side_effect=sqlite3.OperationalError("database is locked")), \
             mock.patch.object(self.instance, "pump_inbox"):
            self.instance.process_ui_queue()
        self.instance.root.after.assert_called_once_with(100, self.instance.process_ui_queue)
        self.assertIn("ui-dispatch", self.instance.faults)


class IncidentEnrollmentTests(IsolatedClientTest):
    def incident_client(self):
        self.instance.root = mock.Mock()
        payload = notification("incident", is_test=True, incident=metadata())
        self.worker()._accept_payload(payload, json.dumps(payload), "incident")
        record = self.instance.inbox.history()[0]
        with mock.patch.object(client, "IncidentResponseWindow") as window:
            self.instance.show_incident_response(record["record_id"])
        return window.call_args.args[1]

    def test_retained_incident_window_is_fenced_by_enrollment_not_only_password(self):
        incident = self.incident_client()
        self.instance.config["endpoints"][0]["desktop_client_id"] = "replacement-enrollment"
        with mock.patch.object(client, "open_http_request") as opened:
            with self.assertRaises(client.UnauthorizedError):
                incident.details()
        opened.assert_not_called()

    def test_late_incident_success_cannot_confirm_a_replaced_enrollment(self):
        incident = self.incident_client()
        def late(*_args, **_kwargs):
            self.instance.config["endpoints"][0]["desktop_client_id"] = "replacement-enrollment"
            return io.BytesIO(json.dumps(projection(response={"response": "safe"})).encode())
        with mock.patch.object(client, "open_http_request", side_effect=late):
            with self.assertRaises(client.UnauthorizedError):
                incident.respond("safe")
        self.assertEqual(incident.pending()["response"], "safe")


class StreamFailureTests(IsolatedClientTest):
    def test_large_retry_field_cannot_abort_following_notification(self):
        for digits, expected in (("9" * 5000, 60_000), ("0" * 5000 + "5", 5)):
            with self.subTest(expected=expected):
                events = list(client.iter_sse_events(io.BytesIO(
                    ("retry: " + digits + "\ndata: accepted\n\n").encode())))
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].data, "accepted")
                self.assertEqual(events[0].retry_ms, expected)

    def test_retry_field_ignores_non_ascii_digits(self):
        events = list(client.iter_sse_events(io.BytesIO("retry: ²\ndata: accepted\n\n".encode())))
        self.assertIsNone(events[0].retry_ms)

    def test_deep_json_and_oversized_integer_do_not_drop_the_next_notification(self):
        for bad in ('[' * 1100 + '0' + ']' * 1100, '9' * 5000):
            with self.subTest(size=len(bad)):
                worker = self.worker()
                good = notification("after-" + str(len(bad)))
                transcript = (authenticated() + ("id: bad\nevent: notification\ndata: " + bad + "\n\n").encode()
                              + sse("notification", good, good["id"]))
                worker._consume_stream(io.BytesIO(transcript))
                self.assertIn(good["id"], [row["event_id"] for row in self.instance.inbox.history()])

    def test_authenticated_padding_does_not_keep_a_stalled_stream_alive(self):
        reader, writer = socket.socketpair()
        reader.settimeout(1)
        response = SocketResponse(reader)
        stop = threading.Event()
        def trickle():
            try:
                writer.sendall(authenticated())
                until = time.monotonic() + 0.4
                while time.monotonic() < until and not stop.wait(0.01):
                    writer.sendall(b":      \n\n")
            except OSError:
                pass
            finally:
                writer.close()
        thread = threading.Thread(target=trickle, daemon=True)
        thread.start()
        worker = self.worker()
        try:
            with mock.patch.object(client, "SSE_TEST_TIMEOUT_SECONDS", 0.08), \
                 mock.patch.object(client, "SSE_READ_TIMEOUT_SECONDS", 0.12):
                started = time.monotonic()
                with self.assertRaises(client.StreamProtocolError):
                    worker._consume_stream(response)
                self.assertLess(time.monotonic() - started, 0.35)
        finally:
            stop.set()
            client.shutdown_socket(reader)
            thread.join(1)
            response.close()
            reader.close()


class ImageBoundaryTests(unittest.TestCase):
    def image_result(self, format):
        from PIL import Image
        source = Image.new("RGB", (16, 8), "red")
        buffer = io.BytesIO()
        source.save(buffer, format=format)
        view = presentation._AlertView.__new__(presentation._AlertView)
        view.item = SimpleNamespace(alert={})
        view.presenter = SimpleNamespace(image_loader=lambda _: buffer.getvalue(), _image_slots=mock.Mock())
        view._image_queue = queue.Queue(maxsize=1)
        view._load_image()
        view.presenter._image_slots.release.assert_called_once()
        return view._image_queue.get_nowait()

    def test_supported_raster_formats_decode_without_constructing_widgets(self):
        for format in ("PNG", "JPEG", "GIF", "WEBP"):
            with self.subTest(format=format):
                self.assertEqual(self.image_result(format).size, (16, 8))

    def test_unneeded_native_image_decoders_are_not_exposed_to_notifications(self):
        for format in ("BMP", "TIFF"):
            with self.subTest(format=format):
                self.assertIsNone(self.image_result(format))


class VoiceDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.voice = "en_US-amy-low"
        self.catalog = copy.deepcopy(voices.read_catalog())
        for entry in self.catalog["files"]:
            entry.update(size=128, sha256=hashlib.sha256(b"a" * 128).hexdigest())
        self.store = voices.VoiceStore(bundled=Path(self.directory.name) / "bundled",
            cache=Path(self.directory.name) / "cache", catalog=self.catalog)

    def slow_response(self):
        reader, writer = socket.socketpair()
        reader.settimeout(2)
        response = SocketResponse(reader)
        stop = threading.Event()
        def send():
            try:
                for _ in range(128):
                    if stop.wait(0.005):
                        return
                    writer.sendall(b"a")
            except OSError:
                pass
            finally:
                writer.close()
        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        def cleanup():
            stop.set()
            client.shutdown_socket(reader)
            thread.join(1)
            response.close()
            reader.close()
        self.addCleanup(cleanup)
        return response

    def test_trickled_voice_download_has_an_absolute_total_deadline(self):
        response = self.slow_response()
        opener = mock.Mock()
        opener.open.side_effect = [response, io.BytesIO(b"a" * 128), io.BytesIO(b"a" * 128)]
        with mock.patch.object(voices, "VOICE_DOWNLOAD_SECONDS", 0.1):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                self.store.download(self.voice, threading.Event(), opener=opener)
            self.assertLess(time.monotonic() - started, 0.5)
        self.assertIsNone(self.store.location(self.voice))
        self.assertFalse(list(self.store.cache.glob(".download-*")))

    def test_cancelling_voice_download_interrupts_a_blocked_read(self):
        response = self.slow_response()
        opener = mock.Mock()
        opener.open.return_value = response
        cancelled = threading.Event()
        timer = threading.Timer(0.08, cancelled.set)
        timer.start()
        try:
            started = time.monotonic()
            self.assertFalse(self.store.download(self.voice, cancelled, opener=opener))
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            timer.cancel()
            timer.join(1)
        self.assertIsNone(self.store.location(self.voice))

    def test_finished_guard_never_closes_a_released_socket(self):
        sock, cancelled = mock.Mock(), threading.Event()
        with voices.TransferDeadline(sock, time.monotonic() + 1, cancelled):
            pass
        cancelled.set()
        sock.shutdown.assert_not_called()

    def test_voice_tls_handler_keeps_certificate_and_hostname_verification(self):
        handler = voices.VoiceHTTPSHandler(time.monotonic() + 1, threading.Event())
        self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(handler._context.check_hostname)


class VoiceHeaderTests(unittest.TestCase):
    def connection(self):
        reader, writer = socket.socketpair()
        reader.settimeout(2)
        cancelled, stopped = threading.Event(), threading.Event()
        connection = voices.VoiceHTTPSConnection("example.invalid", timeout=2,
            transfer_deadline=time.monotonic() + 0.15, cancel_event=cancelled)
        connection.sock = reader
        connection.putrequest("GET", "/synthetic-voice")
        connection.endheaders()

        def trickle():
            try:
                writer.sendall(b"HTTP/1.1 200 OK\r\nX-Synthetic: ")
                while not stopped.wait(0.01):
                    writer.sendall(b"x")
            except OSError:
                pass

        thread = threading.Thread(target=trickle, daemon=True)
        thread.start()

        def cleanup():
            stopped.set()
            client.shutdown_socket(reader)
            client.shutdown_socket(writer)
            thread.join(1)
            connection.close()
            reader.close()
            writer.close()

        self.addCleanup(cleanup)
        return connection, cancelled

    def test_voice_header_trickle_is_interrupted_and_connection_closed(self):
        connection, _ = self.connection()
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            connection.getresponse()
        self.assertLess(time.monotonic() - started, 0.6)
        self.assertIsNone(connection.sock)

    def test_voice_header_cancellation_closes_the_partial_response(self):
        connection, cancelled = self.connection()
        timer = threading.Timer(0.05, cancelled.set)
        timer.start()
        try:
            with self.assertRaises(voices.VoiceDownloadCancelled):
                connection.getresponse()
            self.assertIsNone(connection.sock)
        finally:
            timer.cancel()
            timer.join(1)
