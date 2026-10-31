import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import sll_voices as voices
import sll_mass_notify as client


class VoiceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.catalog = copy.deepcopy(voices.read_catalog())
        self.bodies = {}
        for entry in self.catalog["files"]:
            body = (entry["name"] + " pinned content").encode()
            entry.update(size=len(body), sha256=hashlib.sha256(body).hexdigest())
            self.bodies[entry["url"]] = body
        self.store = voices.VoiceStore(bundled=root / "bundled", cache=root / "cache", catalog=self.catalog)
        self.opener = Mock()
        self.opener.open.side_effect = lambda request, **_: io.BytesIO(self.bodies[request.full_url])
        self.voice = "en_US-amy-low"

    def download(self, voice=None, cancelled=None):
        return self.store.download(voice or self.voice, cancelled or threading.Event(), opener=self.opener)

    def test_download_verifies_and_installs_three_assets_without_pbx_auth(self):
        self.assertIsNone(self.store.location(self.voice))
        self.assertTrue(self.download())
        model = self.store.model(self.voice)
        self.assertEqual(model, self.store.cache / self.voice / (self.voice + ".onnx"))
        self.assertEqual(self.opener.open.call_count, 3)
        for call in self.opener.open.call_args_list:
            self.assertEqual(set(k.lower() for k in call.args[0].headers), {"user-agent"})
        self.assertFalse(list(self.store.cache.glob(".download-*")))
        with patch.object(voices, "VoiceStore", return_value=self.store):
            self.assertTrue(voices.voice_available(self.voice))

    def test_digest_mismatch_preserves_previous_installation_and_cleans_staging(self):
        self.download()
        model = self.store.model(self.voice)
        original = model.read_bytes()
        entry = self.store.entries(self.voice)[0]
        self.bodies[entry["url"]] = b"x" * entry["size"]
        with self.assertRaises(ValueError):
            self.download()
        self.assertEqual(model.read_bytes(), original)
        self.assertFalse(list(self.store.cache.glob(".download-*")))

    def test_oversize_and_truncated_downloads_never_publish(self):
        entry = self.store.entries(self.voice)[0]
        for body in (b"x" * (entry["size"] + 1), b"x"):
            self.bodies[entry["url"]] = body
            with self.assertRaises(ValueError):
                self.download()
            self.assertIsNone(self.store.location(self.voice))
            self.assertFalse(list(self.store.cache.glob(".download-*")))

    def test_cancellation_during_transfer_leaves_no_partial_voice(self):
        cancelled = threading.Event()
        def progress(*_): cancelled.set()
        self.assertFalse(self.store.download(self.voice, cancelled, progress, opener=self.opener))
        self.assertIsNone(self.store.location(self.voice))
        self.assertFalse(list(self.store.cache.glob(".download-*")))

    def test_corruption_after_install_is_rejected_before_model_loading(self):
        self.download()
        model = self.store.model(self.voice)
        model.write_bytes(b"x" * model.stat().st_size)
        with self.assertRaises(ValueError):
            self.store.model(self.voice)

    def test_unknown_voice_and_linked_cache_are_rejected(self):
        with self.assertRaises(ValueError): self.download("../../escape")
        with patch.object(voices, "reject_reparse", side_effect=ValueError("linked path")):
            with self.assertRaises(ValueError): self.download()
        self.opener.open.assert_not_called()

    def test_missing_optional_voice_falls_back_to_included_default(self):
        with patch.object(voices, "voice_available", return_value=False):
            self.assertEqual(voices.playback_voice(self.voice), voices.DEFAULT_VOICE)

    def test_manager_serializes_downloads_reports_progress_and_cancels(self):
        entered = threading.Event()
        def download(voice, cancelled, progress):
            progress(10, 30)
            entered.set()
            cancelled.wait(2)
            return False
        store = Mock()
        store.entries.return_value = [{"size": 30}]
        store.download.side_effect = download
        manager = voices.VoiceDownloads(store)
        self.assertTrue(manager.start(self.voice))
        self.assertTrue(entered.wait(1))
        self.assertFalse(manager.start("es_ES-davefx-medium"))
        self.assertEqual(manager.status()["bytes"], 10)
        manager.cancel()
        manager._thread.join(2)
        self.assertEqual(manager.status()["state"], "cancelled")

    def test_manager_errors_do_not_expose_external_responses(self):
        store = Mock()
        store.entries.return_value = [{"size": 30}]
        store.download.side_effect = ValueError("private response")
        manager = voices.VoiceDownloads(store)
        manager.start(self.voice)
        manager._thread.join(2)
        self.assertEqual(manager.status()["state"], "failed")
        self.assertNotIn("private", str(manager.status()))


class CatalogTests(unittest.TestCase):
    def test_invalid_catalogs_reject_duplicate_paths_urls_and_integrity_fields(self):
        original = voices.read_catalog()
        mutations = [lambda c: c["files"].append(c["files"][0]),
                     lambda c: c["files"][0].update(name="../model"),
                     lambda c: c["files"][0].update(url="https://example.com/model"),
                     lambda c: c["files"][0].update(size=True),
                     lambda c: c["files"][0].update(sha256="invalid")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voices.json"
            for mutate in mutations:
                catalog = copy.deepcopy(original)
                mutate(catalog)
                path.write_text(json.dumps(catalog), encoding="utf-8")
                with self.assertRaises(ValueError): voices.read_catalog(path)

    def test_redirects_reject_http_and_unrelated_hosts(self):
        handler = voices.HTTPSRedirects()
        for url in ("http://huggingface.co/model", "https://example.com/model",
                    "https://huggingface.co.evil.test/model", "https://user:pass@huggingface.co/model"):
            with self.assertRaises(ValueError): handler.redirect_request(None, None, 302, "", {}, url)

    def test_unavailable_selected_voice_cannot_silently_test_another_voice(self):
        window = client.SettingsWindow.__new__(client.SettingsWindow)
        window.app = Mock()
        window.tts_voice_var = Mock(get=lambda: voices.VOICES["en_US-amy-low"])
        window.tts_status_var = Mock()
        with patch.object(client, "voice_available", return_value=False):
            window.test_selected_voice()
        window.app.test_announcement_voice.assert_not_called()
        window.tts_status_var.set.assert_called_once()

    def test_settings_download_is_explicit_and_progress_is_visible(self):
        window = client.SettingsWindow.__new__(client.SettingsWindow)
        window.app = Mock()
        window.tts_voice_var = Mock(get=lambda: voices.VOICES["en_US-amy-low"])
        window.voice_test_button = Mock()
        window.voice_download_button = Mock()
        window.voice_cancel_button = Mock()
        window.voice_download_var = Mock()
        window.app.voice_downloads.status.return_value = {
            "voice": "en_US-amy-low", "state": "downloading", "bytes": 50, "total": 100}
        with patch.object(client, "voice_available", return_value=False):
            window.refresh_voice_controls()
            window.app.voice_downloads.start.assert_not_called()
            window.download_selected_voice()
        window.app.voice_downloads.start.assert_called_once_with("en_US-amy-low")
        self.assertIn("50%", window.voice_download_var.set.call_args.args[0])
        window.voice_test_button.configure.assert_called_with(state="disabled")
        window.voice_cancel_button.configure.assert_called_with(state="normal")


if __name__ == "__main__":
    unittest.main()
