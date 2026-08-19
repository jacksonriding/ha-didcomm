import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ha_didcomm import config
from ha_didcomm import credentials
from ha_didcomm import owner


class OwnerOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store_patch = patch.object(
            config,
            "CREDENTIAL_STORE_PATH",
            str(Path(self.temp_dir.name) / "credentials.sqlite3"),
        )
        self.issuer_patch = patch.object(config, "HOME_ISSUER_DID", "did:key:issuer")
        self.store_patch.start()
        self.issuer_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.addCleanup(self.issuer_patch.stop)

    @patch("ha_didcomm.owner.acapy.issue_credential", new_callable=AsyncMock)
    async def test_issue_persists_credential_after_acapy_accepts(self, issue_credential):
        issue_credential.return_value = {"cred_ex_id": "exchange-1"}

        exchange_id = await owner.issue_access_credential(
            connection_id="connection-1",
            subject_did="did:key:holder",
            role="guest",
            permissions=["light.*"],
            expires="2099-01-01T00:00:00Z",
        )

        self.assertEqual(exchange_id, "exchange-1")
        self.assertTrue(credentials.is_authorised("connection-1", "light.kitchen"))
        issued = issue_credential.await_args.args[1]
        self.assertEqual(issued["credentialSubject"]["id"], "did:key:holder")
        self.assertEqual(issued["expirationDate"], "2099-01-01T00:00:00Z")

    async def test_issue_requires_configured_issuer_and_permissions(self):
        with patch.object(config, "HOME_ISSUER_DID", ""):
            with self.assertRaisesRegex(ValueError, "HOME_ISSUER_DID"):
                await owner.issue_access_credential(
                    connection_id="connection-1",
                    subject_did="did:key:holder",
                    role="guest",
                    permissions=["light.*"],
                )

        with self.assertRaisesRegex(ValueError, "permission"):
            await owner.issue_access_credential(
                connection_id="connection-1",
                subject_did="did:key:holder",
                role="guest",
                permissions=[],
            )


if __name__ == "__main__":
    unittest.main()
