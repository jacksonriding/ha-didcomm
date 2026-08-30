import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import docker_lifecycle_test as lifecycle


class DockerLifecycleTests(unittest.TestCase):
    def test_standalone_wallet_key_uses_equals_form(self):
        compose = lifecycle.COMPOSE_FILE.read_text(encoding="utf-8")

        self.assertIn("--wallet-key=${ACAPY_WALLET_KEY", compose)
        self.assertNotIn("--wallet-key ${ACAPY_WALLET_KEY", compose)

    def test_write_environment_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gateway.env"

            lifecycle.write_environment(path, {"FIRST": "one", "SECOND": "two"})

            self.assertEqual(path.read_text(), "FIRST=one\nSECOND=two\n")

    def test_credential_state_finds_lifecycle_record(self):
        status = {
            "credentials": [
                {
                    "credential_exchange_id": lifecycle.CREDENTIAL_EXCHANGE_ID,
                    "state": "revoked",
                }
            ]
        }

        self.assertEqual(lifecycle.credential_state(status), "revoked")
        self.assertIsNone(lifecycle.credential_state({"credentials": []}))

    @patch("scripts.docker_lifecycle_test.run")
    def test_archive_volume_uses_read_only_source(self, run):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory)

            def create_archive(*_args, **_kwargs):
                (backup / "wallet.tar.gz").write_bytes(b"backup")

            run.side_effect = create_archive
            archive = lifecycle.archive_volume("test-wallet", backup, "wallet.tar.gz")

        self.assertEqual(archive.name, "wallet.tar.gz")
        command = run.call_args.args[0]
        self.assertIn("test-wallet:/source:ro", command)

    @patch("scripts.docker_lifecycle_test.run")
    def test_restore_extracts_into_compose_created_volume(self, run):
        lifecycle.restore_volume(
            "test-wallet", Path("/tmp/test-backup"), "wallet.tar.gz"
        )

        run.assert_called_once()
        self.assertIn("test-wallet:/restore", run.call_args.args[0])

    @patch("scripts.docker_lifecycle_test.run")
    def test_assert_compose_volume_accepts_expected_labels(self, run):
        run.return_value.stdout = (
            '{"com.docker.compose.project":"test-project",'
            '"com.docker.compose.volume":"acapy-wallet"}\n'
        )

        lifecycle.assert_compose_volume(
            "test-wallet", "test-project", "acapy-wallet"
        )

    @patch("scripts.docker_lifecycle_test.run")
    def test_assert_compose_volume_rejects_unlabelled_volume(self, run):
        run.return_value.stdout = "{}\n"

        with self.assertRaisesRegex(
            lifecycle.LifecycleFailure, "Compose-managed volume"
        ):
            lifecycle.assert_compose_volume(
                "test-wallet", "test-project", "acapy-wallet"
            )


if __name__ == "__main__":
    unittest.main()
