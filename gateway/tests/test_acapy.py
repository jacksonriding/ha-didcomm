import unittest
from unittest.mock import AsyncMock, Mock, patch

from ha_didcomm import acapy
from ha_didcomm import config


class AcapyInvitationTests(unittest.IsolatedAsyncioTestCase):
    @patch("ha_didcomm.acapy.httpx.AsyncClient")
    async def test_create_oob_invitation_uses_peer_did_and_did_exchange(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {
            "oob_id": "oob-1",
            "invitation_url": "https://home.example?oob=encoded",
        }
        client.post.return_value = response

        result = await acapy.create_oob_invitation(label="My home", multi_use=True)

        self.assertEqual(result["oob_id"], "oob-1")
        client.post.assert_awaited_once_with(
            f"{config.ACAPY_ADMIN_URL}/out-of-band/create-invitation",
            json={
                "handshake_protocols": ["https://didcomm.org/didexchange/1.1"],
                "protocol_version": "1.1",
                "use_did_method": "did:peer:4",
                "my_label": "My home",
            },
            params={"auto_accept": "true", "multi_use": "true"},
            headers=acapy._headers(),
        )
        response.raise_for_status.assert_called_once_with()

    @patch("ha_didcomm.acapy.httpx.AsyncClient")
    async def test_create_oob_invitation_rejects_missing_url(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"oob_id": "oob-1"}
        client.post.return_value = response

        with self.assertRaisesRegex(ValueError, "invitation_url"):
            await acapy.create_oob_invitation()

    @patch("ha_didcomm.acapy.httpx.AsyncClient")
    async def test_list_connections_returns_records(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {
            "results": [{"connection_id": "connection-1", "state": "active"}]
        }
        client.get.return_value = response

        records = await acapy.list_connections()

        self.assertEqual(records[0]["connection_id"], "connection-1")
        client.get.assert_awaited_once_with(
            f"{config.ACAPY_ADMIN_URL}/connections", headers=acapy._headers()
        )
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
