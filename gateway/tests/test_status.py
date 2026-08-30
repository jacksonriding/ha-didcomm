import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from ha_didcomm import config, credentials, owner, status


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
            patch.object(config, "OWNER_API_TOKEN", "a" * 40),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    @patch("ha_didcomm.status.acapy.list_connections", new_callable=AsyncMock)
    def test_public_status_redacts_connections_and_credentials(
        self, list_connections
    ):
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
        self.assertEqual(body["connections"], [])
        self.assertEqual(body["credentials"], [])
        self.assertEqual(body["connection_count"], 1)
        self.assertEqual(body["credential_counts"], {"active": 1})
        self.assertNotIn("did:key:alice", response.text)
        self.assertNotIn("exchange-1", response.text)

    @patch("ha_didcomm.status.acapy.list_connections", new_callable=AsyncMock)
    def test_owner_status_returns_sanitized_connections_and_credentials(
        self, list_connections
    ):
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
            response = client.get(
                "/owner/status",
                headers={"Authorization": f"Bearer {'a' * 40}"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["instance_id"], "did:key:test-home")
        self.assertEqual(body["connections"][0]["label"], "Alice")
        self.assertNotIn("invitation_key", body["connections"][0])
        self.assertEqual(body["credentials"][0]["state"], "active")
        self.assertEqual(body["credentials"][0]["home_id"], "test-home")
        self.assertEqual(body["credentials"][0]["issuer_did"], "did:key:test-home")
        self.assertEqual(body["credentials"][0]["permissions"], ["light.guest_*"])

    @patch("ha_didcomm.status.acapy.list_connections", new_callable=AsyncMock)
    def test_status_rejects_invalid_acapy_response(self, list_connections):
        list_connections.side_effect = ValueError("invalid response")

        with TestClient(status.app) as client:
            response = client.get("/status")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "ACA-Py is unavailable")

    def test_owner_api_requires_a_strong_configured_bearer_token(self):
        with TestClient(status.app) as client:
            missing = client.get("/owner/health")
            malformed = client.get(
                "/owner/health", headers={"Authorization": "Basic abc"}
            )
            incorrect = client.get(
                "/owner/health", headers={"Authorization": f"Bearer {'b' * 40}"}
            )
            accepted = client.get(
                "/owner/health", headers={"Authorization": f"Bearer {'a' * 40}"}
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(incorrect.status_code, 401)
        self.assertNotIn("a" * 40, incorrect.text)
        self.assertEqual(accepted.json(), {"status": "ok"})

    def test_owner_api_is_unavailable_for_missing_or_placeholder_token(self):
        for token in ("", "short", "replace-with-a-random-owner-token-at-least-32"):
            with (
                self.subTest(token=token),
                patch.object(config, "OWNER_API_TOKEN", token),
                TestClient(status.app) as client,
            ):
                response = client.get("/owner/health")
                self.assertEqual(response.status_code, 503)

    @patch("ha_didcomm.status.acapy.create_oob_invitation", new_callable=AsyncMock)
    def test_owner_creates_safe_invitation(self, create_invitation):
        create_invitation.return_value = {
            "invitation_url": "https://example.test/oob",
            "oob_id": "invitation-1",
            "sensitive": "not-returned",
        }

        with TestClient(status.app) as client:
            response = client.post(
                "/owner/invitations",
                headers={"Authorization": f"Bearer {'a' * 40}"},
                json={"label": "Guest"},
            )

        self.assertEqual(
            response.json(),
            {
                "invitation_url": "https://example.test/oob",
                "oob_id": "invitation-1",
            },
        )
        create_invitation.assert_awaited_once_with(
            label="Guest", multi_use=False, auto_accept=True
        )

    @patch("ha_didcomm.status.owner.issue_access_credential", new_callable=AsyncMock)
    def test_owner_issues_credential_with_server_expiry(self, issue_credential):
        issue_credential.return_value = "exchange-1"
        before = datetime.now(timezone.utc)

        with TestClient(status.app) as client:
            response = client.post(
                "/owner/credentials",
                headers={"Authorization": f"Bearer {'a' * 40}"},
                json={
                    "connection_id": "connection-1",
                    "subject_did": "did:key:guest",
                    "permissions": ["light.guest_*"],
                    "duration_hours": 24,
                },
            )

        after = datetime.now(timezone.utc)
        self.assertEqual(response.status_code, 200)
        expires = datetime.fromisoformat(
            response.json()["expires_at"].replace("Z", "+00:00")
        )
        self.assertGreaterEqual(expires, before + status.timedelta(hours=24))
        self.assertLessEqual(expires, after + status.timedelta(hours=24))
        self.assertEqual(response.json()["cred_ex_id"], "exchange-1")
        self.assertEqual(issue_credential.await_args.kwargs["role"], "guest")
        self.assertEqual(
            issue_credential.await_args.kwargs["expires"], response.json()["expires_at"]
        )

    @patch("ha_didcomm.status.owner.issue_access_credential", new_callable=AsyncMock)
    def test_owner_reports_duplicate_active_grant_as_conflict(self, issue_credential):
        issue_credential.side_effect = owner.EquivalentActiveGrantError()

        with TestClient(status.app) as client:
            response = client.post(
                "/owner/credentials",
                headers={"Authorization": f"Bearer {'a' * 40}"},
                json={
                    "connection_id": "connection-1",
                    "subject_did": "did:key:guest",
                    "permissions": ["light.guest_*"],
                    "duration_hours": 24,
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"], "An equivalent active grant already exists"
        )

    def test_owner_rejects_invalid_credential_input(self):
        headers = {"Authorization": f"Bearer {'a' * 40}"}
        with TestClient(status.app) as client:
            empty_permissions = client.post(
                "/owner/credentials",
                headers=headers,
                json={
                    "connection_id": "connection-1",
                    "subject_did": "did:key:guest",
                    "permissions": [],
                    "duration_hours": 24,
                },
            )
            excessive_duration = client.post(
                "/owner/credentials",
                headers=headers,
                json={
                    "connection_id": "connection-1",
                    "subject_did": "did:key:guest",
                    "permissions": ["light.*"],
                    "duration_hours": 8761,
                },
            )
            connection_id_as_subject = client.post(
                "/owner/credentials",
                headers=headers,
                json={
                    "connection_id": "connection-1",
                    "subject_did": "1295f0cb-c24f-4056-a806-3c046eff46d1",
                    "permissions": ["light.*"],
                    "duration_hours": 24,
                },
            )

        self.assertEqual(empty_permissions.status_code, 422)
        self.assertEqual(excessive_duration.status_code, 422)
        self.assertEqual(connection_id_as_subject.status_code, 422)

    @patch("ha_didcomm.status.credentials.revoke_credential")
    @patch("ha_didcomm.status.credentials.revoke_connection")
    def test_owner_revocation_and_unknown_records(
        self, revoke_connection, revoke_credential
    ):
        revoke_credential.side_effect = [True, False]
        revoke_connection.return_value = True
        headers = {"Authorization": f"Bearer {'a' * 40}"}
        with TestClient(status.app) as client:
            credential = client.post(
                "/owner/credentials/exchange-1/revoke", headers=headers, json={}
            )
            unknown = client.post(
                "/owner/credentials/unknown/revoke", headers=headers, json={}
            )
            connection = client.post(
                "/owner/connections/connection-1/revoke", headers=headers, json={}
            )

        self.assertEqual(credential.status_code, 200)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(connection.status_code, 200)

    @patch("ha_didcomm.status.acapy.create_oob_invitation", new_callable=AsyncMock)
    def test_owner_sanitizes_upstream_failures(self, create_invitation):
        create_invitation.side_effect = httpx.ConnectError("secret upstream URL")
        with TestClient(status.app) as client:
            response = client.post(
                "/owner/invitations",
                headers={"Authorization": f"Bearer {'a' * 40}"},
                json={},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "ACA-Py is unavailable")
        self.assertNotIn("secret upstream URL", response.text)


if __name__ == "__main__":
    unittest.main()
