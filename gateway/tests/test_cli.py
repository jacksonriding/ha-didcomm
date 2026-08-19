import io
import unittest
from unittest.mock import AsyncMock, patch

from ha_didcomm import cli


class OnboardingCliTests(unittest.TestCase):
    @patch("ha_didcomm.cli.acapy.create_oob_invitation", new_callable=AsyncMock)
    def test_invite_prints_qr_and_url(self, create_invitation):
        invitation_url = "https://home.example/invite?oob=encoded-invitation"
        create_invitation.return_value = {"invitation_url": invitation_url}
        output = io.StringIO()

        with patch("sys.stdout", output):
            result = cli.main(["invite", "--label", "Jackson home"])

        self.assertEqual(result, 0)
        self.assertIn(invitation_url, output.getvalue())
        self.assertTrue(any(character in output.getvalue() for character in "█▀▄"))
        create_invitation.assert_awaited_once_with(
            label="Jackson home", multi_use=False, auto_accept=True
        )

    @patch("ha_didcomm.cli.acapy.create_oob_invitation", new_callable=AsyncMock)
    def test_invite_options_are_forwarded(self, create_invitation):
        create_invitation.return_value = {"invitation_url": "https://example.test/oob"}

        with patch("sys.stdout", io.StringIO()):
            cli.main(["invite", "--multi-use", "--manual-accept"])

        create_invitation.assert_awaited_once_with(
            label=None, multi_use=True, auto_accept=False
        )

    def test_qr_renderer_has_quiet_border_and_consistent_width(self):
        rendered = cli.render_terminal_qr("https://example.test/oob")
        lines = rendered.splitlines()

        self.assertGreater(len(lines), 10)
        self.assertEqual(len({len(line) for line in lines}), 1)
        self.assertTrue(lines[0].isspace())
        self.assertTrue(lines[-1].isspace())

    @patch("ha_didcomm.cli.acapy.list_connections", new_callable=AsyncMock)
    def test_connections_lists_owner_relevant_fields(self, list_connections):
        list_connections.return_value = [
            {
                "connection_id": "connection-1",
                "rfc23_state": "completed",
                "their_label": "Alice",
                "their_did": "did:peer:4alice",
            }
        ]
        output = io.StringIO()

        with patch("sys.stdout", output):
            cli.main(["connections"])

        self.assertIn("connection-1\tcompleted\tAlice\tdid:peer:4alice", output.getvalue())

    @patch("ha_didcomm.cli.owner.issue_access_credential", new_callable=AsyncMock)
    def test_issue_accepts_multiple_permission_patterns(self, issue_credential):
        issue_credential.return_value = "exchange-1"
        output = io.StringIO()

        with patch("sys.stdout", output):
            cli.main(
                [
                    "issue",
                    "connection-1",
                    "did:key:holder",
                    "--permission",
                    "light.*",
                    "--permission",
                    "switch.guest_room",
                    "--expires",
                    "2026-08-20T00:00:00Z",
                ]
            )

        issue_credential.assert_awaited_once_with(
            connection_id="connection-1",
            subject_did="did:key:holder",
            role="guest",
            permissions=["light.*", "switch.guest_room"],
            expires="2026-08-20T00:00:00Z",
        )
        self.assertIn("exchange-1", output.getvalue())

    @patch("ha_didcomm.cli.credentials.revoke_credential", return_value=True)
    def test_revoke_credential_reports_success(self, revoke_credential):
        output = io.StringIO()

        with patch("sys.stdout", output):
            cli.main(["revoke-credential", "exchange-1"])

        revoke_credential.assert_called_once_with("exchange-1")
        self.assertIn("exchange-1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
