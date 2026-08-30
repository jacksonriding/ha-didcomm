import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch
from urllib.error import URLError

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

    def test_persistent_secret_is_safe_as_a_command_option_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            value = addon.persistent_secret(Path(temp_dir) / "wallet-key")

        self.assertRegex(value, re.compile(r"^[0-9a-f]{64}$"))

    def test_acapy_command_uses_equals_form_for_wallet_key(self):
        command = addon.acapy_start_command(
            {"public_endpoint": "https://ha.local:8000"},
            "-leading-hyphen-secret",
            "info",
        )

        self.assertIn("--wallet-key=-leading-hyphen-secret", command)
        self.assertNotIn("--wallet-key", command)

    def test_admin_request_adds_api_key(self):
        request = addon.admin_request("http://localhost/status", "secret")

        self.assertEqual(request.get_header("X-api-key"), "secret")

    def test_gateway_environment_propagates_owner_token(self):
        environment = addon.gateway_environment(
            {"home_id": "test-home", "owner_api_token": "owner-secret"},
            "admin-secret",
            "did:key:issuer",
        )

        self.assertEqual(environment["OWNER_API_TOKEN"], "owner-secret")
        self.assertEqual(environment["ACAPY_ADMIN_API_KEY"], "admin-secret")
        self.assertEqual(environment["HOME_ISSUER_DID"], "did:key:issuer")

    def test_gateway_environment_uses_safe_defaults(self):
        environment = addon.gateway_environment({}, "admin-secret", "did:key:issuer")

        self.assertEqual(environment["HOME_ID"], "home")
        self.assertEqual(environment["OWNER_API_TOKEN"], "")

    @patch("ha_didcomm.addon.urlopen")
    def test_wait_for_admin_returns_when_ready(self, urlopen):
        process = Mock()
        process.poll.return_value = None

        addon.wait_for_admin(process, "admin-secret", attempts=1)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, f"{addon.ADMIN_URL}/status/live")
        self.assertEqual(request.get_header("X-api-key"), "admin-secret")

    def test_wait_for_admin_fails_immediately_when_agent_exits(self):
        process = Mock()
        process.poll.return_value = 2

        with self.assertRaisesRegex(RuntimeError, "exited before"):
            addon.wait_for_admin(process, "admin-secret", attempts=3)

    @patch("ha_didcomm.addon.time.sleep")
    @patch("ha_didcomm.addon.urlopen", side_effect=URLError("not ready"))
    def test_wait_for_admin_times_out_after_bounded_retries(self, urlopen, sleep):
        process = Mock()
        process.poll.return_value = None

        with self.assertRaisesRegex(RuntimeError, "did not become ready"):
            addon.wait_for_admin(process, "admin-secret", attempts=2)

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleep.call_args_list, [call(0.5), call(0.5)])

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

    @patch("ha_didcomm.addon.urlopen")
    def test_issuer_did_is_reused_after_restore(self, urlopen):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "issuer-did"
            path.write_text("did:key:restored", encoding="utf-8")

            did = addon.issuer_did(path, "admin-secret")

        self.assertEqual(did, "did:key:restored")
        urlopen.assert_not_called()

    def test_tls_file_rejects_traversal_and_requires_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            certificate = directory / "fullchain.pem"
            certificate.write_text("certificate", encoding="utf-8")

            self.assertEqual(addon.tls_file("fullchain.pem", directory), certificate)
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
        self.assertIn("location /owner/", nginx_config)
        self.assertIn("proxy_pass http://127.0.0.1:8090", nginx_config)
        self.assertNotIn("8021", nginx_config)

    @patch("ha_didcomm.addon.load_options")
    def test_main_rejects_non_https_public_endpoint(self, load_options):
        load_options.return_value = {"public_endpoint": "http://home.example"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(addon, "DATA_DIR", Path(temp_dir)):
                with self.assertRaisesRegex(ValueError, "must use HTTPS"):
                    addon.main()

    @patch("ha_didcomm.addon.signal.signal")
    @patch("ha_didcomm.addon.issuer_did", return_value="did:key:issuer")
    @patch("ha_didcomm.addon.wait_for_admin")
    @patch("ha_didcomm.addon.persistent_secret")
    @patch("ha_didcomm.addon.write_nginx_config")
    @patch("ha_didcomm.addon.tls_file")
    @patch("ha_didcomm.addon.load_options")
    @patch("ha_didcomm.addon.subprocess.Popen")
    def test_main_starts_services_returns_failure_and_cleans_up(
        self,
        popen,
        load_options,
        tls_file,
        write_nginx_config,
        persistent_secret,
        wait_for_admin,
        issuer_did,
        signal_handler,
    ):
        load_options.return_value = {
            "public_endpoint": "https://home.example",
            "certfile": "fullchain.pem",
            "keyfile": "privkey.pem",
            "owner_api_token": "owner-secret",
        }
        tls_file.side_effect = [Path("/ssl/fullchain.pem"), Path("/ssl/privkey.pem")]
        persistent_secret.side_effect = ["wallet-secret", "admin-secret"]
        acapy_process = Mock(returncode=0)
        gateway_process = Mock(returncode=7)
        status_process = Mock(returncode=0)
        nginx_process = Mock(returncode=0)
        acapy_process.poll.return_value = None
        gateway_process.poll.return_value = 7
        status_process.poll.return_value = None
        nginx_process.poll.return_value = None
        popen.side_effect = [
            acapy_process,
            gateway_process,
            status_process,
            nginx_process,
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(addon, "DATA_DIR", Path(temp_dir)):
                with patch.object(
                    addon, "NGINX_CONFIG_PATH", Path(temp_dir) / "nginx.conf"
                ):
                    result = addon.main()

        self.assertEqual(result, 7)
        wait_for_admin.assert_called_once_with(acapy_process, "admin-secret")
        self.assertIn("--wallet-key=wallet-secret", popen.call_args_list[0].args[0])
        gateway_environment = popen.call_args_list[1].kwargs["env"]
        self.assertEqual(gateway_environment["OWNER_API_TOKEN"], "owner-secret")
        self.assertIn("ha_didcomm.main:app", popen.call_args_list[1].args[0])
        self.assertIn("ha_didcomm.status:app", popen.call_args_list[2].args[0])
        self.assertEqual(popen.call_args_list[3].args[0][0], "nginx")
        acapy_process.terminate.assert_called_once_with()
        status_process.terminate.assert_called_once_with()
        nginx_process.terminate.assert_called_once_with()
        gateway_process.terminate.assert_not_called()
        self.assertEqual(signal_handler.call_count, 2)
