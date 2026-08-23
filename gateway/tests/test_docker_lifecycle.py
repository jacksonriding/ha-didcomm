import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import docker_lifecycle_test as lifecycle


class DockerLifecycleTests(unittest.TestCase):
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
    def test_restore_creates_volume_before_extracting(self, run):
        lifecycle.restore_volume(
            "test-wallet", Path("/tmp/test-backup"), "wallet.tar.gz"
        )

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["docker", "volume", "create", "test-wallet"],
        )
        self.assertIn("test-wallet:/restore", run.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
