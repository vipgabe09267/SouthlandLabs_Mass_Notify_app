"""Build security policy rejects stale runtimes and dependency provenance."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

from tools import check_build_runtime as runtime
with mock.patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1] / 'tools'), *sys.path]):
    from tools import verify_build_artifacts as artifacts


class RuntimePolicyTests(unittest.TestCase):
    def check_runtime(self, python, openssl):
        with mock.patch.object(runtime.sys, 'version_info', python), \
             mock.patch.object(runtime.sys, 'platform', 'win32'), \
             mock.patch.object(runtime.sys, 'argv', ['check_build_runtime.py', '--release']), \
             mock.patch.object(runtime.platform, 'python_implementation', return_value='CPython'), \
             mock.patch.object(runtime.platform, 'machine', return_value='AMD64'), \
             mock.patch.object(runtime.ssl, 'OPENSSL_VERSION', openssl), \
             mock.patch('builtins.print'):
            runtime.main()

    def test_current_reviewed_runtime_is_accepted(self):
        self.check_runtime((3,14,9), 'OpenSSL 3.5.9 29 Sep 2026')

    def test_previous_python_runtime_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.check_runtime((3,14,7), 'OpenSSL 3.5.9 29 Sep 2026')

    def test_previous_tls_patch_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.check_runtime((3,14,9), 'OpenSSL 3.5.8 25 Aug 2026')


class PackageInventoryTests(unittest.TestCase):
    def setUp(self):
        self.packages=[]
        for line in (artifacts.ROOT / 'requirements-build.txt').read_text().splitlines():
            found=re.match(r'([A-Za-z0-9_-]+)==([^ ]+)',line)
            if found:
                self.packages.append({'name':found[1], 'version':found[2]})

    def test_reviewed_packages_accept_canonical_metadata_names(self):
        for package in self.packages:
            package['name']=package['name'].upper().replace('-', '_')
        artifacts.verify_locked_packages(self.packages)

    def test_stale_or_extra_package_is_rejected(self):
        with self.subTest('stale'):
            self.packages[0]['version']='0.0.0'
            with self.assertRaises(ValueError):
                artifacts.verify_locked_packages(self.packages)
        with self.subTest('extra'):
            self.setUp()
            self.packages.append({'name':'unreviewed', 'version':'1.0'})
            with self.assertRaises(ValueError):
                artifacts.verify_locked_packages(self.packages)

    def test_duplicate_canonical_package_is_rejected(self):
        self.packages.append(dict(self.packages[0]))
        with self.assertRaises(ValueError):
            artifacts.verify_locked_packages(self.packages)


class NativeRuntimeTests(unittest.TestCase):
    def test_old_tls_library_cannot_pass_using_current_inventory_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base, package = root / "python", root / "app"
            (base / "DLLs").mkdir(parents=True)
            (package / "_internal").mkdir(parents=True)
            names = ("python314.dll", "_ssl.pyd", "libssl-3.dll", "libcrypto-3.dll", "_sqlite3.pyd", "sqlite3.dll")
            for name in names:
                source = base / name if name == "python314.dll" else base / "DLLs" / name
                source.write_bytes(b"reviewed runtime fixture")
                (package / "_internal" / name).write_bytes(source.read_bytes())
            with mock.patch.object(artifacts.sys, "base_prefix", str(base)):
                artifacts.verify_runtime_binaries(package)
                for name in ("libssl-3.dll", "libcrypto-3.dll", "sqlite3.dll"):
                    with self.subTest(library=name):
                        candidate = package / "_internal" / name
                        candidate.write_bytes(b"previous runtime fixture")
                        with self.assertRaisesRegex(ValueError, name):
                            artifacts.verify_runtime_binaries(package)
                        candidate.write_bytes(b"reviewed runtime fixture")
