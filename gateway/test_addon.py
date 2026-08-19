import json
import tempfile
import unittest
from pathlib import Path

import addon


class AddonTests(unittest.TestCase):
    def test_load_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "options.json"
            path.write_text(
                json.dumps({"public_endpoint": "http://ha.local:8000"}),
                encoding="utf-8",
            )
            self.assertEqual(addon.load_options(path)["public_endpoint"], "http://ha.local:8000")

    def test_load_options_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "options.json"
            path.write_text('{"home_id":"home"}', encoding="utf-8-sig")
            self.assertEqual(addon.load_options(path)["home_id"], "home")

    def test_persistent_secret_is_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "wallet-key"
            first = addon.persistent_secret(path)
            second = addon.persistent_secret(path)
            self.assertEqual(first, second)
            self.assertGreater(len(first), 30)
