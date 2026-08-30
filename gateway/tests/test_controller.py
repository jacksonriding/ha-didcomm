import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from ha_didcomm import controller


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def test_response_store_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.sqlite"
            with patch.object(controller, "RESPONSE_STORE_PATH", str(path)):
                with controller._connect_store() as connection:
                    connection.execute("SELECT 1")

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_headers_add_admin_key_only_when_configured(self):
        with patch.object(controller, "ADMIN_API_KEY", ""):
            self.assertEqual(controller._headers(), {"Content-Type": "application/json"})
        with patch.object(controller, "ADMIN_API_KEY", "admin-secret"):
            self.assertEqual(controller._headers()["X-API-Key"], "admin-secret")

    def test_decodes_oob_invitation_url(self):
        invitation = {"@type": "https://didcomm.org/out-of-band/1.1/invitation", "@id": "1"}
        encoded = base64.urlsafe_b64encode(json.dumps(invitation).encode()).decode().rstrip("=")

        self.assertEqual(
            controller.decode_invitation_url(f"https://home.example/invite?_oob={encoded}"),
            invitation,
        )

    def test_extracts_invitation_url_from_owner_action_response(self):
        invitation = {"@id": "invite-1"}
        encoded = base64.urlsafe_b64encode(json.dumps(invitation).encode()).decode().rstrip("=")
        url = f"https://home.example/invite?oob={encoded}"
        response_text = f'{{% set action_response = {{"invitation_url":"{url}"}} %}}'

        self.assertEqual(controller.extract_invitation_url(response_text), url)
        self.assertEqual(controller.decode_invitation_url(response_text), invitation)

    def test_extracts_invitation_url_from_json_response(self):
        invitation = {"@id": "invite-json"}
        encoded = base64.urlsafe_b64encode(json.dumps(invitation).encode()).decode().rstrip("=")
        url = f"https://home.example/invite?_oob={encoded}"

        self.assertEqual(
            controller.extract_invitation_url(json.dumps({"invitation_url": url})),
            url,
        )

    def test_rejects_ambiguous_invitation_input(self):
        encoded = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
        first = f"https://one.example/invite?oob={encoded}"
        second = f"https://two.example/invite?_oob={encoded}"

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            controller.extract_invitation_url(f"{first} {second}")

    def test_rejects_duplicate_oob_parameters(self):
        encoded = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")

        with self.assertRaises(ValueError):
            controller.decode_invitation_url(
                f"https://home.example/invite?oob={encoded}&_oob={encoded}"
            )

    def test_rejects_empty_missing_and_malformed_invitation_data(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            controller.extract_invitation_url("   ")
        with self.assertRaisesRegex(ValueError, "no _oob or oob"):
            controller.extract_invitation_url("ftp://home.example/invite?oob=value")
        with self.assertRaisesRegex(ValueError, "invalid OOB data"):
            controller.decode_invitation_url("https://home.example/invite?oob=not-json")

        encoded = base64.urlsafe_b64encode(b"[]").decode().rstrip("=")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            controller.decode_invitation_url(f"https://home.example/invite?oob={encoded}")

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_reuses_existing_key(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"results": [{"did": "did:key:existing"}]}
        client.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                self.assertEqual(await controller.holder_did(), "did:key:existing")
                self.assertEqual(
                    controller._get_setting("holder_did"), "did:key:existing"
                )
                client.post.assert_not_awaited()

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_creates_and_persists_when_wallet_is_empty(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        empty = Mock()
        empty.json.return_value = {"results": []}
        created = Mock()
        created.json.return_value = {"result": {"did": "did:key:created"}}
        client.get.return_value = empty
        client.post.return_value = created

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                self.assertEqual(await controller.holder_did(), "did:key:created")
                self.assertEqual(
                    controller._get_setting("holder_did"), "did:key:created"
                )

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_fails_when_saved_identity_is_missing(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"results": [{"did": "did:key:other"}]}
        client.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                controller._set_setting("holder_did", "did:key:saved")
                with self.assertRaisesRegex(ValueError, "saved controller identity"):
                    await controller.holder_did()
                client.post.assert_not_awaited()

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_reuses_saved_identity_among_multiple_keys(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {
            "results": [{"did": "did:key:saved"}, {"did": "did:key:other"}]
        }
        client.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                controller._set_setting("holder_did", "did:key:saved")
                self.assertEqual(await controller.holder_did(), "did:key:saved")
                client.post.assert_not_awaited()

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_fails_closed_with_multiple_unsaved_keys(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {
            "results": [{"did": "did:key:one"}, {"did": "did:key:two"}]
        }
        client.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                with self.assertRaisesRegex(ValueError, "multiple did:key"):
                    await controller.holder_did()

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_explicitly_selects_existing_key(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {
            "results": [{"did": "did:key:one"}, {"did": "did:key:two"}]
        }
        client.get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                self.assertEqual(
                    await controller.holder_did("did:key:two"), "did:key:two"
                )
                self.assertEqual(controller._get_setting("holder_did"), "did:key:two")

    async def test_holder_did_rejects_non_key_selector_before_admin_request(self):
        with self.assertRaisesRegex(ValueError, "must be a did:key"):
            await controller.holder_did("did:web:controller.example")

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_rejects_invalid_wallet_records(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"results": "not-a-list"}
        client.get.return_value = response

        with self.assertRaisesRegex(ValueError, "wallet DID records"):
            await controller.holder_did()

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_rejects_missing_explicit_identity(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"results": [{"did": "did:key:other"}]}
        client.get.return_value = response

        with self.assertRaisesRegex(ValueError, "selected controller identity"):
            await controller.holder_did("did:key:missing")

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_holder_did_rejects_invalid_created_identity(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        empty = Mock()
        empty.json.return_value = {"results": []}
        created = Mock()
        created.json.return_value = {"result": {"did": "did:web:wrong"}}
        client.get.return_value = empty
        client.post.return_value = created

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                with self.assertRaisesRegex(ValueError, "did:key identity"):
                    await controller.holder_did()

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

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_accept_invitation_rejects_non_object_admin_response(self, client_type):
        encoded = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = []
        client.post.return_value = response

        with self.assertRaisesRegex(ValueError, "invalid connection record"):
            await controller.accept_invitation(f"https://home.test?oob={encoded}")

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_list_connections_validates_admin_response(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        response = Mock()
        client.get.return_value = response

        response.json.return_value = {"results": [{"connection_id": "connection-1"}]}
        self.assertEqual(
            await controller.list_connections(),
            [{"connection_id": "connection-1"}],
        )

        response.json.return_value = {"results": ["invalid"]}
        with self.assertRaisesRegex(ValueError, "connection records"):
            await controller.list_connections()

    async def test_response_store_ignores_invalid_ids_and_reports_missing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"
            ):
                controller._store_response({"id": True, "result": "ignored"})
                controller._store_response({"result": "ignored"})
                self.assertIsNone(controller._get_response("True"))
                self.assertIsNone(controller._get_response("missing"))

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_call_service_sends_json_rpc_and_returns_matching_response(
        self, client_type
    ):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        client.post.return_value = Mock()
        expected = {"jsonrpc": "2.0", "id": "request-1", "result": {"executed": True}}

        with patch.object(controller.uuid, "uuid4", return_value="request-1"):
            with patch.object(
                controller, "_get_response", side_effect=[None, expected]
            ):
                with patch.object(controller.asyncio, "sleep", new_callable=AsyncMock):
                    result = await controller.call_service(
                        "connection-1", "turn_on", "light.office", 1
                    )

        self.assertEqual(result, expected)
        sent = json.loads(client.post.await_args.kwargs["json"]["content"])
        self.assertEqual(sent["id"], "request-1")
        self.assertEqual(
            sent["params"],
            {"action": "turn_on", "entity_id": "light.office"},
        )

    @patch("ha_didcomm.controller.httpx.AsyncClient")
    async def test_call_service_times_out_without_response(self, client_type):
        client = AsyncMock()
        client_type.return_value.__aenter__.return_value = client
        client.post.return_value = Mock()

        with self.assertRaisesRegex(TimeoutError, "no reply received"):
            await controller.call_service(
                "connection-1", "turn_on", "light.office", 0
            )

    async def test_health_and_webhook_ignore_untrusted_payloads(self):
        self.assertEqual(await controller.health(), {"status": "ok"})
        request = Mock()
        request.json = AsyncMock(
            side_effect=[
                {"state": "received", "content": "not-json"},
                {"state": "received", "content": "[]"},
                {"state": "pending", "content": '{"jsonrpc":"2.0","id":"x"}'},
            ]
        )

        self.assertEqual(await controller.webhook("basicmessages", request), {"ok": True})
        self.assertEqual(await controller.webhook("basicmessages", request), {"ok": True})
        self.assertEqual(await controller.webhook("other", request), {"ok": True})

    def test_print_connections_normalizes_missing_values(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            controller._print_connections(
                [
                    {
                        "connection_id": "connection-1",
                        "state": "active",
                        "their_label": "",
                    }
                ]
            )

        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "CONNECTION ID\tSTATE\tLABEL\tTHEIR DID",
                "connection-1\tactive\t-\t-",
            ],
        )

    async def test_webhook_persists_json_rpc_response(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(controller, "RESPONSE_STORE_PATH", f"{directory}/responses.sqlite"):
                request = Mock()
                request.json = AsyncMock(
                    return_value={
                        "state": "received",
                        "content": json.dumps(
                            {"jsonrpc": "2.0", "id": "request-1", "result": {"executed": True}}
                        ),
                    }
                )
                response = await controller.webhook("basicmessages", request)

                self.assertEqual(response, {"ok": True})
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

    @patch("ha_didcomm.controller.holder_did", new_callable=AsyncMock)
    def test_identity_accepts_explicit_did_selector(self, holder_did):
        holder_did.return_value = "did:key:selected"
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = controller.main(["identity", "--did", "did:key:selected"])

        self.assertEqual(result, 0)
        holder_did.assert_awaited_once_with("did:key:selected")

    @patch("ha_didcomm.controller.accept_invitation", new_callable=AsyncMock)
    def test_connect_reads_invitation_from_stdin(self, accept_invitation):
        accept_invitation.return_value = {"connection_id": "connection-1"}
        with patch("sys.stdin", io.StringIO("https://home.test?oob=value\n")):
            with patch("sys.stdout", io.StringIO()):
                result = controller.main(["connect", "--stdin"])

        self.assertEqual(result, 0)
        accept_invitation.assert_awaited_once_with("https://home.test?oob=value\n")

    @patch("ha_didcomm.controller.accept_invitation", new_callable=AsyncMock)
    def test_connect_retains_positional_input(self, accept_invitation):
        accept_invitation.return_value = {"connection_id": "connection-1"}
        with patch("sys.stdout", io.StringIO()):
            result = controller.main(["connect", "https://home.test?oob=value"])

        self.assertEqual(result, 0)
        accept_invitation.assert_awaited_once_with("https://home.test?oob=value")

    @patch("ha_didcomm.controller.accept_invitation", new_callable=AsyncMock)
    def test_connect_rejects_mixed_and_oversized_input(self, accept_invitation):
        with patch("sys.stdin", io.StringIO("stdin invitation")):
            with self.assertRaises(SystemExit) as mixed:
                controller.main(["connect", "positional", "--stdin"])
        self.assertEqual(mixed.exception.code, 1)

        oversized = "x" * (controller._MAX_INVITATION_INPUT_BYTES + 1)
        with patch("sys.stdin", io.StringIO(oversized)):
            with self.assertRaises(SystemExit) as too_large:
                controller.main(["connect", "--stdin"])
        self.assertEqual(too_large.exception.code, 1)
        accept_invitation.assert_not_awaited()

    @patch("ha_didcomm.controller.list_connections", new_callable=AsyncMock)
    def test_connections_prints_records(self, list_connections):
        list_connections.return_value = [
            {"connection_id": "connection-1", "rfc23_state": "completed"}
        ]
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = controller.main(["connections"])

        self.assertEqual(result, 0)
        self.assertIn("connection-1\tcompleted", output.getvalue())

    @patch("ha_didcomm.controller.call_service", new_callable=AsyncMock)
    def test_call_returns_rpc_status_and_prints_json(self, call_service):
        call_service.return_value = {"jsonrpc": "2.0", "id": "1", "result": {}}
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = controller.main(
                ["call", "connection-1", "turn_on", "light.office", "--timeout", "3"]
            )
        self.assertEqual(result, 0)
        self.assertIn('"result": {}', output.getvalue())
        call_service.assert_awaited_once_with(
            "connection-1", "turn_on", "light.office", 3.0
        )

        call_service.return_value = {"jsonrpc": "2.0", "id": "2", "error": {}}
        with patch("sys.stdout", io.StringIO()):
            result = controller.main(
                ["call", "connection-1", "turn_on", "light.office"]
            )
        self.assertEqual(result, 2)

    @patch("ha_didcomm.controller.accept_invitation", new_callable=AsyncMock)
    def test_cli_reports_http_errors_without_traceback(self, accept_invitation):
        request = httpx.Request("POST", "https://home.test")
        response = httpx.Response(503, request=request)
        accept_invitation.side_effect = httpx.HTTPStatusError(
            "unavailable", request=request, response=response
        )

        with self.assertRaises(SystemExit) as raised:
            controller.main(["connect", "https://home.test?oob=value"])

        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
