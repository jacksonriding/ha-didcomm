import io
import unittest
from unittest.mock import AsyncMock, patch

import cli


class OnboardingCliTests(unittest.TestCase):
    @patch("cli.acapy.create_oob_invitation", new_callable=AsyncMock)
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

    @patch("cli.acapy.create_oob_invitation", new_callable=AsyncMock)
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


if __name__ == "__main__":
    unittest.main()
