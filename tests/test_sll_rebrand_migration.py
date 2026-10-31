"""Rebrand upgrades use isolated files; no real registry, shortcuts or clients."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import sll_legacy as legacy
import sll_installer as installer
import sll_install_safety as safety


class StableIdentityTests(unittest.TestCase):
    def test_renamed_product_keeps_the_registered_upgrade_identity(self):
        self.assertEqual(installer.APP_DISPLAY_NAME, "Southland Labs Mass Notify")
        self.assertEqual(installer.COMPANY_DISPLAY_NAME, "Southland Labs")
        self.assertEqual(installer.EXE_NAME, "SLL_Mass_Notify.exe")
        self.assertEqual(installer.UNINSTALL_REG_PATH, legacy.UNINSTALL_REG_PATH)
        self.assertEqual(safety.PRODUCT_ID, legacy.PRODUCT_ID)
        self.assertEqual(safety.MANIFEST_NAME, legacy.MANIFEST_NAME)
        self.assertEqual(safety.TRANSACTION_NAME, legacy.TRANSACTION_NAME)
        self.assertEqual(installer.DEFAULT_INSTALL_DIR.parts[-2:], ("Southland Labs", "SLL Mass Notify"))

    def test_old_per_user_state_and_optional_voices_stay_at_the_same_paths(self):
        with mock.patch.dict(os.environ, APPDATA="roaming", LOCALAPPDATA="local"):
            self.assertEqual(legacy.config_directory(), Path("roaming") / legacy.COMPANY_NAME / legacy.APP_SHORT_NAME)
            self.assertEqual(legacy.voice_cache_directory(), Path("local") / legacy.COMPANY_NAME / legacy.APP_SHORT_NAME / "voices")

    def test_shutdown_checks_both_exact_executable_paths(self):
        root = Path("fixture")
        report = mock.Mock()
        with mock.patch.object(installer, "close_exact_processes") as close:
            installer.stop_running_app(root, report)
        self.assertEqual(close.call_args_list, [
            mock.call(root / installer.EXE_NAME, force=True, progress=report),
            mock.call(root / legacy.EXE_NAME, force=True, progress=report),
        ])

    def test_registry_snapshot_validation_never_recalculates_install_size(self):
        root = Path("fixture-install")
        values = {"DisplayName": [legacy.APP_DISPLAY_NAME, 1], "InstallLocation": [str(root), 1]}
        with mock.patch.object(installer, "uninstall_registry_values", side_effect=AssertionError("Unexpected size scan")), \
                mock.patch.object(Path, "rglob", side_effect=AssertionError("Unexpected tree walk")):
            validated = installer.validated_registration(values, root, "1.0.13-beta")
        self.assertEqual(validated["DisplayName"], (legacy.APP_DISPLAY_NAME, 1))


class BrandedUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "previous-install"
        (self.root / ".maintenance").mkdir(parents=True)
        (self.root / legacy.EXE_NAME).write_bytes(b"previous desktop")
        self.old_setup = self.root / ".maintenance" / legacy.SETUP_EXE_NAME
        self.old_setup.write_bytes(b"previous maintenance")
        self.shared = self.root / "default-voice.onnx"
        self.shared.write_bytes(b"unchanged voice")
        self.shared_identity = self.shared.stat().st_ino
        (self.root / installer.DEFAULTS_NAME).write_text(json.dumps({
            "startup_enabled": True, "auto_update_enabled": False,
        }))
        self.old_links = {name: self.base / f"old-{name}.lnk" for name in ("application", "uninstall", "startup")}
        self.new_links = {name: self.base / f"new-{name}.lnk" for name in self.old_links}
        for name, path in self.old_links.items():
            path.write_bytes(("owned old " + name).encode())
        self.previous = safety.manifest_for(self.root, version="1.0.13-beta", shortcuts={
            name: safety.digest(path) for name, path in self.old_links.items()
        })
        safety.write_json(self.root / safety.MANIFEST_NAME, self.previous)
        (self.root / "customer-notes.txt").write_bytes(b"unowned retained")
        self.original_files = {name: (self.root / name).read_bytes() for name in self.previous["files"]}
        self.original_links = {name: path.read_bytes() for name, path in self.old_links.items()}
        self.registration = {"DisplayName": (legacy.APP_DISPLAY_NAME, 1), "InstallLocation": (str(self.root), 1)}
        for name in ("require_admin", "verify_protected_directory", "protect_new_directory", "stop_running_app", "create_protected_directories"):
            self.enterContext(mock.patch.object(installer, name))
        self.enterContext(mock.patch.object(installer, "validate_install_dir", return_value=self.root))
        self.enterContext(mock.patch.object(installer, "machine_shortcuts", return_value=self.new_links))
        self.enterContext(mock.patch.object(installer, "legacy_machine_shortcuts", return_value=self.old_links))
        self.enterContext(mock.patch.object(installer, "snapshot_uninstall_registry", return_value=self.registration))
        self.restore = self.enterContext(mock.patch.object(installer, "restore_uninstall_registry"))
        self.real_register = installer.write_uninstall_registry
        self.register = self.enterContext(mock.patch.object(installer, "write_uninstall_registry"))
        self.stage = self.enterContext(mock.patch.object(installer, "stage_payload", side_effect=self.stage_payload))
        self.enterContext(mock.patch.object(installer, "create_shortcut", side_effect=lambda path, target, **kw: path.write_bytes(str(target).encode())))

    def stage_payload(self, stage):
        (stage / installer.EXE_NAME).write_bytes(b"current desktop")
        (stage / ".maintenance").mkdir()
        (stage / ".maintenance" / "SLL_Mass_Notify_Installer.exe").write_bytes(b"current maintenance")
        (stage / self.shared.name).write_bytes(self.shared.read_bytes())

    def install(self, **options):
        installer.install_app(self.root, startup=options.get("startup"), launch=False,
                              remove_legacy=False, auto_update=None)

    def assert_previous_restored(self):
        self.assertEqual(safety.read_manifest(self.root), self.previous)
        for name, content in self.original_files.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        for name, content in self.original_links.items():
            self.assertEqual(self.old_links[name].read_bytes(), content)
        self.assertFalse(any(path.exists() for path in self.new_links.values()))
        self.assertFalse((self.root / installer.EXE_NAME).exists())
        self.assertEqual((self.root / "customer-notes.txt").read_bytes(), b"unowned retained")

    def test_upgrade_retires_owned_executables_and_shortcuts_without_duplicates(self):
        self.install()
        manifest = safety.read_manifest(self.root)
        self.assertEqual(manifest["version"], installer.APP_VERSION)
        self.assertEqual((self.root / installer.EXE_NAME).read_bytes(), b"current desktop")
        self.assertFalse((self.root / legacy.EXE_NAME).exists())
        self.assertFalse(self.old_setup.exists())
        self.assertFalse(any(path.exists() for path in self.old_links.values()))
        self.assertTrue(all(path.is_file() for path in self.new_links.values()))
        self.assertEqual(manifest["shortcuts"], {name: safety.digest(path) for name, path in self.new_links.items()})
        self.assertEqual(self.shared.stat().st_ino, self.shared_identity)
        self.assertEqual((self.root / "customer-notes.txt").read_bytes(), b"unowned retained")
        self.assertEqual(json.loads((self.root / installer.DEFAULTS_NAME).read_text()), {
            "startup_enabled": True, "auto_update_enabled": False,
        })
        self.restore.assert_not_called()

    def test_failed_registration_restores_old_names_links_registry_and_payload(self):
        self.register.side_effect = OSError("registration failed")
        with self.assertRaisesRegex(OSError, "registration failed"):
            self.install()
        self.assert_previous_restored()
        self.restore.assert_called_once_with(self.registration)

    def test_partial_new_shortcut_failure_restores_every_old_link(self):
        create = installer.create_shortcut
        def failed(path, target, **options):
            if path.name == "uninstall.lnk":
                raise OSError("shortcut failed")
            return create(path, target, **options)
        with mock.patch.object(installer, "create_shortcut", side_effect=failed):
            with self.assertRaisesRegex(OSError, "shortcut failed"):
                self.install()
        self.assert_previous_restored()

    def test_unowned_new_shortcut_collision_prevents_all_upgrade_work(self):
        collision = self.new_links["application"]
        collision.write_bytes(b"another application")
        with self.assertRaisesRegex(ValueError, "unowned or changed shortcut"):
            self.install()
        self.stage.assert_not_called()
        self.assertEqual(collision.read_bytes(), b"another application")
        self.assertEqual(safety.read_manifest(self.root), self.previous)
        self.assertTrue(all(path.exists() for path in self.old_links.values()))

    def test_modified_old_shortcut_prevents_all_upgrade_work(self):
        self.old_links["application"].write_bytes(b"changed old link")
        with self.assertRaisesRegex(ValueError, "unowned or changed shortcut"):
            self.install()
        self.stage.assert_not_called()
        self.assertEqual(self.old_links["application"].read_bytes(), b"changed old link")
        self.assertTrue((self.root / legacy.EXE_NAME).is_file())

    def test_disabled_startup_retires_old_link_without_creating_a_replacement(self):
        self.install(startup=False)
        self.assertFalse(self.new_links["startup"].exists())
        self.assertFalse(self.old_links["startup"].exists())
        self.assertNotIn("startup", safety.read_manifest(self.root)["shortcuts"])

    def test_second_upgrade_uses_current_owned_shortcut_names(self):
        self.install()
        self.old_links["application"].write_bytes(b"unowned unrelated link")
        self.install()
        self.assertEqual(self.old_links["application"].read_bytes(), b"unowned unrelated link")
        self.assertTrue(all(path.exists() for path in self.new_links.values()))

    def interrupted_upgrade(self):
        stage = self.base / "interrupted-stage"
        stage.mkdir()
        self.stage_payload(stage)
        intended = safety.manifest_for(stage, version=installer.APP_VERSION)
        transaction = safety.FileTransaction(self.root, stage, intended, previous=self.previous)
        transaction.__enter__()
        snapshots = installer.validate_shortcut_ownership(self.previous)
        planned, _ = installer.stage_integration(transaction, self.root, snapshots, self.registration, startup=True)
        return transaction, planned, snapshots

    def recover(self):
        return safety.recover_interrupted_upgrade(self.root, integration_recovery=installer.prepare_integration_recovery)

    def edit_journal(self, change):
        path = self.root / safety.TRANSACTION_NAME
        value = json.loads(path.read_text())
        change(value)
        safety.write_json(path, value)

    def assert_interrupted_files_retained(self):
        self.assertTrue((self.root / safety.TRANSACTION_NAME).is_file())
        self.assertEqual((self.root / installer.EXE_NAME).read_bytes(), b"current desktop")
        self.assertFalse((self.root / legacy.EXE_NAME).exists())

    def test_crash_after_retiring_old_links_recovers_both_file_and_machine_names(self):
        _, planned, snapshots = self.interrupted_upgrade()
        installer.apply_staged_shortcuts(planned, snapshots)
        self.assertFalse(any(path.exists() for path in self.old_links.values()))
        self.assertTrue(self.recover())
        self.assert_previous_restored()
        self.assertFalse(self.recover())
        self.restore.assert_called_once_with(self.registration)

    def test_real_registration_publishes_frozen_size_despite_journal_growth(self):
        _, planned, snapshots = self.interrupted_upgrade()
        frozen = json.loads((self.root / safety.TRANSACTION_NAME).read_text())["integration"]["registry"]["after"]
        # The snapshot itself enlarged the root journal after this size was
        # captured. Publishing a recomputed value would be a third state.
        self.assertGreater(installer.uninstall_registry_values(self.root)["EstimatedSize"][0], frozen["EstimatedSize"][0])
        installer.apply_staged_shortcuts(planned, snapshots)
        current = dict(self.registration)
        registry = mock.MagicMock()
        registry.SetValueEx.side_effect = lambda key, name, reserved, kind, data: current.__setitem__(name, (data, kind))
        with mock.patch.object(installer, "winreg", registry):
            self.real_register(self.root, values=frozen)
        self.assertEqual(current["EstimatedSize"][0], frozen["EstimatedSize"][0])
        with mock.patch.object(installer, "snapshot_uninstall_registry", return_value=current):
            self.assertTrue(self.recover())
        self.assert_previous_restored()
        self.restore.assert_called_once_with(self.registration)

    def test_crash_between_new_shortcuts_remains_recoverable(self):
        _, planned, snapshots = self.interrupted_upgrade()
        replace = installer.os.replace
        class PowerLoss(BaseException):
            pass
        def interrupted(source, target):
            if target == self.new_links["uninstall"]:
                raise PowerLoss()
            return replace(source, target)
        with mock.patch.object(installer.os, "replace", side_effect=interrupted):
            with self.assertRaises(PowerLoss):
                installer.apply_staged_shortcuts(planned, snapshots)
        self.assertTrue(self.new_links["application"].exists())
        self.assertTrue(self.recover())
        self.assert_previous_restored()

    def test_recovery_interrupted_during_registration_can_be_retried(self):
        _, planned, snapshots = self.interrupted_upgrade()
        installer.apply_staged_shortcuts(planned, snapshots)
        self.restore.side_effect = [OSError("temporary registry failure"), None]
        with self.assertRaisesRegex(OSError, "temporary registry failure"):
            self.recover()
        self.assertTrue((self.root / safety.TRANSACTION_NAME).exists())
        self.assertTrue(self.recover())
        self.assert_previous_restored()
        self.assertEqual(self.restore.call_count, 2)

    def test_recovery_requires_machine_handler_before_touching_files(self):
        self.interrupted_upgrade()
        with self.assertRaisesRegex(ValueError, "Machine integration recovery is required"):
            safety.recover_interrupted_upgrade(self.root)
        self.assert_interrupted_files_retained()

    def test_recovery_rejects_arbitrary_shortcut_paths_before_touching_files(self):
        self.interrupted_upgrade()
        self.edit_journal(lambda value: value["integration"]["shortcuts"].update({
            str(self.base / "unrelated.lnk"): {"before": None, "after": None},
        }))
        with self.assertRaisesRegex(ValueError, "invalid machine shortcut names"):
            self.recover()
        self.assert_interrupted_files_retained()
        self.restore.assert_not_called()

    def test_recovery_rejects_unowned_old_shortcut_bytes(self):
        self.interrupted_upgrade()
        self.edit_journal(lambda value: value["integration"]["shortcuts"]["legacy:application"].update({
            "before": base64.b64encode(b"forged executable link").decode(),
        }))
        with self.assertRaisesRegex(ValueError, "does not match its owned hash"):
            self.recover()
        self.assert_interrupted_files_retained()
        self.restore.assert_not_called()

    def test_recovery_rejects_external_uninstall_command(self):
        self.interrupted_upgrade()
        self.edit_journal(lambda value: value["integration"]["registry"]["before"].update({
            "UninstallString": ['"C:\\unrelated.exe" --uninstall', 1],
        }))
        with self.assertRaisesRegex(ValueError, "another registered product or path"):
            self.recover()
        self.assert_interrupted_files_retained()
        self.restore.assert_not_called()

    def test_recovery_rejects_unknown_registry_field(self):
        self.interrupted_upgrade()
        self.edit_journal(lambda value: value["integration"]["registry"]["before"].update({
            "UnexpectedExecutable": ["run.exe", 1],
        }))
        with self.assertRaisesRegex(ValueError, "invalid uninstall registry fields"):
            self.recover()
        self.assert_interrupted_files_retained()

    def test_recovery_rejects_registry_type_confusion(self):
        self.interrupted_upgrade()
        self.edit_journal(lambda value: value["integration"]["registry"]["after"].update({
            "EstimatedSize": [True, 4],
        }))
        with self.assertRaisesRegex(ValueError, "invalid uninstall registry number"):
            self.recover()
        self.assert_interrupted_files_retained()

    def test_recovery_preserves_new_shortcut_modified_after_interruption(self):
        _, planned, snapshots = self.interrupted_upgrade()
        installer.apply_staged_shortcuts(planned, snapshots)
        self.new_links["application"].write_bytes(b"unrelated replacement")
        with self.assertRaisesRegex(ValueError, "changed after interruption"):
            self.recover()
        self.assert_interrupted_files_retained()
        self.assertEqual(self.new_links["application"].read_bytes(), b"unrelated replacement")
        self.restore.assert_not_called()

    def test_recovery_preserves_registration_modified_after_interruption(self):
        self.interrupted_upgrade()
        changed = dict(self.registration, DisplayName=("Unrelated product", 1))
        with mock.patch.object(installer, "snapshot_uninstall_registry", return_value=changed):
            with self.assertRaisesRegex(ValueError, "registration changed after interruption"):
                self.recover()
        self.assert_interrupted_files_retained()
        self.restore.assert_not_called()


if __name__ == "__main__":
    unittest.main()
