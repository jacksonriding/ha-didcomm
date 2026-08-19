import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ha_didcomm import addon


class AddonTests(unittest.TestCase):
    def test_load_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "options.json"
            path.write_text(
                json.dumps({"public_endpoint": "https://ha.local:8000"}),
                encoding="utf-8",
            )
            self.assertEqual(
                addon.load_options(path)["public_endpoint"],
                "https://ha.local:8000",
            )

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

    def test_admin_request_adds_api_key(self):
        request = addon.admin_request("http://localhost/status", "secret")

        self.assertEqual(request.get_header("X-api-key"), "secret")

    @patch("ha_didcomm.addon.urlopen")
    def test_issuer_did_uses_authenticated_request(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"result":{"did":"did:key:test"}}'
        response.headers.get_content_charset.return_value = "utf-8"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "issuer-did"

            did = addon.issuer_did(path, "admin-secret")

        self.assertEqual(did, "did:key:test")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), "admin-secret")

    def test_tls_file_rejects_traversal_and_requires_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            certificate = directory / "fullchain.pem"
            certificate.write_text("certificate", encoding="utf-8")

            self.assertEqual(
                addon.tls_file("fullchain.pem", directory), certificate
            )
            with self.assertRaises(ValueError):
                addon.tls_file("../fullchain.pem", directory)
            with self.assertRaises(FileNotFoundError):
                addon.tls_file("missing.pem", directory)

    def test_write_nginx_config_keeps_admin_routes_internal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nginx.conf"
            addon.write_nginx_config(
                Path("/ssl/fullchain.pem"),
                Path("/ssl/privkey.pem"),
                path,
            )
            nginx_config = path.read_text(encoding="utf-8")

        self.assertIn("listen 8443 ssl", nginx_config)
        self.assertIn("proxy_pass http://127.0.0.1:8000", nginx_config)
        self.assertIn("location = /status", nginx_config)
        self.assertNotIn("8021", nginx_config)
