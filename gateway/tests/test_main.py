import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from ha_didcomm import config
from ha_didcomm import credentials
from ha_didcomm import main


class RevocationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        store_path = str(Path(self.temp_dir.name) / "credentials.sqlite3")
        self.path_patch = patch.object(config, "CREDENTIAL_STORE_PATH", store_path)
        self.issuer_patch = patch.object(
            config, "HOME_ISSUER_DID", "did:key:issuer"
        )
        self.path_patch.start()
        self.issuer_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.issuer_patch.stop)

        self.credential = credentials.build_credential(
            subject_did="did:key:holder",
            issuer_did="did:key:issuer",
            role="guest",
            permissions=["light.*"],
        )

    def test_revoke_credential_endpoint(self):
        credentials.remember_issued("connection-1", self.credential, "exchange-1")

        with TestClient(main.app) as client:
            response = client.post("/admin/revoke-credential/exchange-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"revoked": True, "cred_ex_id": "exchange-1"})
        self.assertFalse(credentials.is_authorised("connection-1", "light.kitchen"))

    def test_revoke_connection_endpoint_and_unknown_record(self):
        credentials.remember_issued("connection-1", self.credential, "exchange-1")

        with TestClient(main.app) as client:
            response = client.post("/admin/revoke-connection/connection-1")
            missing = client.post("/admin/revoke-credential/unknown")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(missing.status_code, 404)

    @patch("ha_didcomm.main.acapy.send_basic_message", new_callable=AsyncMock)
    @patch("ha_didcomm.main.home_assistant.call_service", new_callable=AsyncMock)
    def test_rpc_command_executes_and_replies(self, call_service, send_message):
        credentials.remember_issued("connection-1", self.credential, "exchange-1")
        request = {
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "homeassistant.call_service",
            "params": {"action": "turn_on", "entity_id": "light.kitchen"},
        }

        asyncio.run(
            main._handle_basic_message(
                {
                    "state": "received",
                    "connection_id": "connection-1",
                    "content": json.dumps(request),
                }
            )
        )

        call_service.assert_awaited_once_with("light", "turn_on", "light.kitchen")
        response = json.loads(send_message.await_args.args[1])
        self.assertTrue(response["result"]["executed"])

    @patch("ha_didcomm.main.acapy.send_basic_message", new_callable=AsyncMock)
    @patch("ha_didcomm.main.home_assistant.call_service", new_callable=AsyncMock)
    def test_unauthorised_rpc_command_returns_error(self, call_service, send_message):
        request = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "homeassistant.call_service",
            "params": {"action": "turn_on", "entity_id": "light.kitchen"},
        }

        asyncio.run(
            main._handle_basic_message(
                {
                    "state": "received",
                    "connection_id": "connection-1",
                    "content": json.dumps(request),
                }
            )
        )

        call_service.assert_not_awaited()
        response = json.loads(send_message.await_args.args[1])
        self.assertEqual(response["error"]["code"], -32001)


if __name__ == "__main__":
    unittest.main()
