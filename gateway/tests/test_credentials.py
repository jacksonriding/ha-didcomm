from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ha_didcomm import config
from ha_didcomm import credentials


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store_path = str(
            Path(self.temp_dir.name) / "nested" / "credentials.sqlite3"
        )
        self.path_patch = patch.object(config, "CREDENTIAL_STORE_PATH", self.store_path)
        self.home_patch = patch.object(config, "HOME_ID", "home-a")
        self.issuer_patch = patch.object(config, "HOME_ISSUER_DID", "did:key:issuer")
        self.path_patch.start()
        self.home_patch.start()
        self.issuer_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.home_patch.stop)
        self.addCleanup(self.issuer_patch.stop)

    def credential(self, permissions=None, expires=None):
        return credentials.build_credential(
            subject_did="did:key:holder",
            issuer_did="did:key:issuer",
            role="guest",
            permissions=permissions or ["light.guest_*"],
            expires_iso=expires,
        )

    def test_credential_survives_fresh_store_connection(self):
        credentials.remember_issued("connection-1", self.credential(), "exchange-1")

        # Authorization opens the database afresh instead of using process memory.
        self.assertTrue(credentials.is_authorised("connection-1", "light.guest_room"))
        self.assertFalse(credentials.is_authorised("connection-2", "light.guest_room"))

        with closing(sqlite3.connect(self.store_path)) as connection:
            stored = connection.execute(
                "SELECT connection_id, credential_exchange_id FROM issued_credentials"
            ).fetchone()
        self.assertEqual(stored, ("connection-1", "exchange-1"))

    def test_permissions_remain_connection_scoped(self):
        credentials.remember_issued("connection-1", self.credential(["light.*"]))

        self.assertTrue(credentials.is_authorised("connection-1", "light.kitchen"))
        self.assertFalse(credentials.is_authorised("connection-1", "switch.kitchen"))
        self.assertFalse(credentials.is_authorised("connection-2", "light.kitchen"))

    def test_credentials_remain_home_and_issuer_scoped(self):
        valid = self.credential(["light.*"])
        wrong_home = self.credential(["light.*"])
        wrong_home["credentialSubject"]["home"] = "home-b"
        wrong_issuer = self.credential(["light.*"])
        wrong_issuer["issuer"] = "did:key:other-home"

        credentials.remember_issued("valid", valid, "exchange-valid")
        credentials.remember_issued("wrong-home", wrong_home, "exchange-home")
        credentials.remember_issued("wrong-issuer", wrong_issuer, "exchange-issuer")

        self.assertTrue(credentials.is_authorised("valid", "light.kitchen"))
        self.assertFalse(credentials.is_authorised("wrong-home", "light.kitchen"))
        self.assertFalse(credentials.is_authorised("wrong-issuer", "light.kitchen"))

        records = {record["id"]: record for record in credentials.list_issued()}
        self.assertEqual(records["exchange-valid"]["state"], "active")
        self.assertEqual(records["exchange-home"]["state"], "invalid")
        self.assertEqual(records["exchange-issuer"]["state"], "invalid")
        self.assertEqual(records["exchange-valid"]["home_id"], "home-a")
        self.assertEqual(records["exchange-valid"]["issuer_did"], "did:key:issuer")

    def test_same_guest_can_have_isolated_access_at_two_homes(self):
        guest_did = "did:key:shared-guest"
        home_a_store = self.store_path
        home_b_store = str(
            Path(self.temp_dir.name) / "home-b" / "credentials.sqlite3"
        )

        credential_a = credentials.build_credential(
            guest_did,
            "did:key:issuer",
            "guest",
            ["light.guest_room"],
        )
        credentials.remember_issued("connection-a", credential_a, "exchange-a")

        with (
            patch.object(config, "CREDENTIAL_STORE_PATH", home_b_store),
            patch.object(config, "HOME_ID", "home-b"),
            patch.object(config, "HOME_ISSUER_DID", "did:key:issuer-b"),
        ):
            credential_b = credentials.build_credential(
                guest_did,
                "did:key:issuer-b",
                "visitor",
                ["lock.front_door"],
            )
            credentials.remember_issued("connection-b", credential_b, "exchange-b")

            self.assertTrue(
                credentials.is_authorised("connection-b", "lock.front_door")
            )
            self.assertFalse(
                credentials.is_authorised("connection-b", "light.guest_room")
            )

            credentials.remember_issued(
                "connection-b", credential_a, "foreign-exchange"
            )
            self.assertFalse(
                credentials.is_authorised("connection-b", "light.guest_room")
            )
            self.assertTrue(credentials.revoke_credential("exchange-b"))
            self.assertFalse(
                credentials.is_authorised("connection-b", "lock.front_door")
            )

        self.assertEqual(config.CREDENTIAL_STORE_PATH, home_a_store)
        self.assertTrue(
            credentials.is_authorised("connection-a", "light.guest_room")
        )
        self.assertFalse(credentials.is_authorised("connection-a", "lock.front_door"))

    def test_expired_and_invalid_expiry_credentials_fail_closed(self):
        credentials.remember_issued(
            "expired", self.credential(expires="2020-01-01T00:00:00Z")
        )
        credentials.remember_issued("invalid", self.credential(expires="not-a-date"))
        credentials.remember_issued(
            "naive", self.credential(expires="2099-01-01T00:00:00")
        )

        self.assertFalse(credentials.is_authorised("expired", "light.guest_room"))
        self.assertFalse(credentials.is_authorised("invalid", "light.guest_room"))
        self.assertFalse(credentials.is_authorised("naive", "light.guest_room"))

    def test_malformed_stored_record_is_ignored(self):
        credentials.initialize_store()
        with closing(sqlite3.connect(self.store_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO issued_credentials
                        (connection_id, credential_json, created_at)
                    VALUES (?, ?, ?)
                    """,
                    ("connection-1", json.dumps(["not", "a", "credential"]), "now"),
                )

        self.assertFalse(credentials.is_authorised("connection-1", "light.guest_room"))

    def test_malformed_credential_fields_fail_closed(self):
        malformed = self.credential()
        malformed["type"] = None
        malformed["expirationDate"] = ["not", "a", "date"]
        credentials.remember_issued("connection-1", malformed)

        self.assertFalse(credentials.is_authorised("connection-1", "light.guest_room"))

    def test_revoked_credential_is_no_longer_authorised(self):
        credentials.remember_issued("connection-1", self.credential(), "exchange-1")
        self.assertTrue(credentials.is_authorised("connection-1", "light.guest_room"))

        self.assertTrue(credentials.revoke_credential("exchange-1"))
        self.assertTrue(credentials.revoke_credential("exchange-1"))
        self.assertFalse(credentials.is_authorised("connection-1", "light.guest_room"))
        self.assertFalse(credentials.revoke_credential("unknown"))

    def test_revoking_connection_does_not_affect_other_connections(self):
        credentials.remember_issued("connection-1", self.credential(), "exchange-1")
        credentials.remember_issued("connection-2", self.credential(), "exchange-2")

        self.assertTrue(credentials.revoke_connection("connection-1"))
        self.assertFalse(credentials.is_authorised("connection-1", "light.guest_room"))
        self.assertTrue(credentials.is_authorised("connection-2", "light.guest_room"))
        self.assertFalse(credentials.revoke_connection("unknown"))

    def test_existing_database_is_migrated_for_revocation(self):
        Path(self.store_path).parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.store_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE issued_credentials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        connection_id TEXT NOT NULL,
                        credential_exchange_id TEXT,
                        credential_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO issued_credentials (
                        connection_id, credential_exchange_id,
                        credential_json, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "legacy-connection",
                        "legacy-exchange",
                        json.dumps(self.credential()),
                        "2026-08-16T00:00:00+00:00",
                    ),
                )

        credentials.initialize_store()

        with closing(sqlite3.connect(self.store_path)) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(issued_credentials)"
                ).fetchall()
            }
        self.assertIn("revoked_at", columns)
        self.assertTrue(
            credentials.is_authorised("legacy-connection", "light.guest_room")
        )
        self.assertTrue(credentials.revoke_credential("legacy-exchange"))
        self.assertFalse(
            credentials.is_authorised("legacy-connection", "light.guest_room")
        )

    def test_list_issued_reports_active_expired_and_revoked_records(self):
        credentials.remember_issued("active", self.credential(), "exchange-active")
        credentials.remember_issued(
            "expired",
            self.credential(expires="2020-01-01T00:00:00Z"),
            "exchange-expired",
        )
        credentials.remember_issued("revoked", self.credential(), "exchange-revoked")
        credentials.revoke_credential("exchange-revoked")

        records = {record["id"]: record for record in credentials.list_issued()}

        self.assertEqual(records["exchange-active"]["state"], "active")
        self.assertEqual(records["exchange-expired"]["state"], "expired")
        self.assertEqual(records["exchange-revoked"]["state"], "revoked")
        self.assertEqual(records["exchange-active"]["role"], "guest")


if __name__ == "__main__":
    unittest.main()
