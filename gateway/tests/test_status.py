import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from ha_didcomm import config
from ha_didcomm import credentials
from ha_didcomm import status


class StatusApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patches = [
            patch.object(
                config,
                "CREDENTIAL_STORE_PATH",
                str(Path(self.temp_dir.name) / "credentials.sqlite3"),
            ),
            patch.object(config, "HOME_ID", "test-home"),
            patch.object(config, "HOME_ISSUER_DID", "did:key:test-home"),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    @patch("ha_didcomm.status.acapy.list_connections", new_callable=AsyncMock)
    def test_status_returns_sanitized_connections_and_credentials(self, list_connections):
        list_connections.return_value = [
            {
                "connection_id": "connection-1",
                "state": "completed",
                "their_label": "Alice",
                "their_did": "did:peer:4alice",
                "invitation_key": "must-not-leak",
            }
        ]
        credential = credentials.build_credential(
            "did:key:alice",
            "did:key:test-home",
            "guest",
            ["light.guest_*"],
        )
        credentials.remember_issued("connection-1", credential, "exchange-1")

        with TestClient(status.app) as client:
            response = client.get("/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["instance_id"], "did:key:test-home")
        self.assertEqual(body["connections"][0]["label"], "Alice")
        self.assertNotIn("invitation_key", body["connections"][0])
        self.assertEqual(body["credentials"][0]["state"], "active")
        self.assertEqual(body["credentials"][0]["permissions"], ["light.guest_*"])

    @patch("ha_didcomm.status.acapy.list_connections", new_callable=AsyncMock)
    def test_status_rejects_invalid_acapy_response(self, list_connections):
        list_connections.side_effect = ValueError("invalid response")

        with TestClient(status.app) as client:
            response = client.get("/status")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "ACA-Py is unavailable")


if __name__ == "__main__":
    unittest.main()
