import base64
import io
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from ha_didcomm import controller


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def test_decodes_oob_invitation_url(self):
        invitation = {"@type": "https://didcomm.org/out-of-band/1.1/invitation", "@id": "1"}
        encoded = base64.urlsafe_b64encode(json.dumps(invitation).encode()).decode().rstrip("=")

        self.assertEqual(
            controller.decode_invitation_url(f"https://home.example/invite?_oob={encoded}"),
            invitation,
        )

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_reuses_existing_key(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"results": [{"did": "did:key:existing"}]}
        client.get.return_value = response

        self.assertEqual(await controller.holder_did(), "did:key:existing")
        client.post.assert_not_awaited()

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_accept_invitation_posts_decoded_json(self, client_type):
        invitation = {"@id": "invite-1"}
        encoded = base64.urlsafe_b64encode(json.dumps(invitation).encode()).decode().rstrip("=")
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"connection_id": "connection-1"}
        client.post.return_value = response

        result = await controller.accept_invitation(f"https://home.test?oob={encoded}")

        self.assertEqual(result["connection_id"], "connection-1")
        client.post.assert_awaited_once_with(
            f"{controller.ADMIN_URL}/out-of-band/receive-invitation",
            params={"auto_accept": "true"},
            json=invitation,
            headers=controller._headers(),
        )

    def test_webhook_persists_json_rpc_response(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"):
                client = TestClient(controller.app)
                response = client.post(
                    "/topic/basicmessages/",
                    json={
                        "state": "received",
                        "content": json.dumps(
                            {"jsonrpc": "2.0", "id": "request-1", "result": {"executed": True}}
                        ),
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    controller._get_response("request-1")["result"], {"executed": True}
                )


class ControllerCliTests(unittest.TestCase):
    @patch("ha_didcomm.controller.holder_did", new_callable=AsyncMock)
    def test_identity_prints_holder_did(self, holder_did):
        holder_did.return_value = "did:key:holder"
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = controller.main(["identity"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "did:key:holder")


if __name__ == "__main__":
    unittest.main()
