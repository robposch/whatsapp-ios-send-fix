"""Regression tests for the WhatsApp send-fix scripts.

Guards two behaviours that previously broke on severely-corrupt databases:
  * wa_fix_send.quick_check_ok must return False (not crash) when SQLite raises
    "database disk image is malformed".
  * wa_send_diagnose.quick_check must classify that as MALFORMED (the bug),
    not a generic ERROR.

Plus a privacy gate: the synthetic fixtures (and their .recover output) must
contain no JIDs / phone numbers.

Run:  python3 -m unittest discover tests
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, HERE)  # so infra_schema / build_fixture / pii_scan import

import build_fixture  # noqa: E402
import pii_scan  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wa_fix = _load("wa_fix_send", "wa_fix_send.py")
wa_diag = _load("wa_send_diagnose", "wa_send_diagnose.py")


class InfraFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wa_fixture_")
        cls.valid = build_fixture.build_valid(os.path.join(cls.tmp, "infra_valid.sqlite"))
        cls.malformed = build_fixture.build_malformed(os.path.join(cls.tmp, "infra_malformed.sqlite"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_fixtures_have_no_pii(self):
        self.assertEqual(pii_scan.scan(self.valid), [])
        self.assertEqual(pii_scan.scan(self.malformed), [])
        # The salvaged output must also be clean.
        rec = subprocess.run(["sqlite3", self.malformed, ".recover"],
                             capture_output=True, text=True).stdout
        out = os.path.join(self.tmp, "recovered.sqlite")
        subprocess.run(["sqlite3", out], input=rec, text=True, check=True)
        self.assertEqual(pii_scan.scan(out), [])

    def test_quick_check_ok_false_on_malformed(self):
        # Must not raise; severe corruption -> False so callers proceed to recover.
        self.assertFalse(wa_fix.quick_check_ok(self.malformed))

    def test_quick_check_ok_true_on_valid(self):
        self.assertTrue(wa_fix.quick_check_ok(self.valid))

    def test_diagnose_classifies_malformed(self):
        status, _detail = wa_diag.quick_check(self.malformed)
        self.assertEqual(status, "MALFORMED")

    def test_diagnose_classifies_valid_ok(self):
        status, _detail = wa_diag.quick_check(self.valid)
        self.assertEqual(status, "OK")

    def test_recover_salvages_malformed(self):
        out = os.path.join(self.tmp, "salvaged.sqlite")
        with open(self.malformed, "rb") as f:
            data = f.read()
        wa_fix.sqlite_recover(data, out)  # raises on failure
        self.assertTrue(wa_fix.quick_check_ok(out))


if __name__ == "__main__":
    unittest.main()
