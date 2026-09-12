"""Verifiable-credential based authorization (v0.0.3).

Replaces the v0.0.2 static config/policies.yaml allowlist with real W3C
verifiable credentials (JSON-LD, ld_proof), issued to a connection via
ACA-Py's Issue Credential 2.0 protocol.

Issuer-side records remain the authority for scope, expiry, and revocation.
The command handler additionally requires a fresh signed presentation through
proofs.py, enabled by the upstream ACA-Py DIF holder-signing fix (#4196).

Credentials use JSON-LD (ld_proof) so no ledger/schema registration is
needed: the @context is defined inline, and DIDs are did:key identities
(issuer = the home's did:key, subject = the remote party's did:key).
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from fnmatch import fnmatch
import json
import hashlib
from pathlib import Path
import sqlite3

from . import config

CREDENTIAL_TYPE = "SmartHomeAccessCredential"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS issued_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id TEXT NOT NULL,
    credential_exchange_id TEXT,
    credential_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_issued_credentials_connection
    ON issued_credentials (connection_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_issued_credentials_exchange
    ON issued_credentials (credential_exchange_id)
    WHERE credential_exchange_id IS NOT NULL;
"""


def _connect() -> sqlite3.Connection:
    database_path = Path(config.CREDENTIAL_STORE_PATH)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5)
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_store() -> None:
    """Create the credential store schema if it does not already exist."""
    with closing(_connect()) as connection:
        with connection:
            connection.executescript(_SCHEMA)
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(issued_credentials)"
                ).fetchall()
            }
            if "revoked_at" not in columns:
                connection.execute(
                    "ALTER TABLE issued_credentials ADD COLUMN revoked_at TEXT"
                )


def build_credential(
    subject_did: str,
    issuer_did: str,
    role: str,
    permissions: list[str],
    expires_iso: str | None = None,
) -> dict:
    credential = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            {
                "sh": "https://ha-didcomm.dev/credentials#",
                "SmartHomeAccessCredential": "sh:SmartHomeAccessCredential",
                "home": "sh:home",
                "role": "sh:role",
                "permissions": "sh:permissions",
            },
        ],
        "type": ["VerifiableCredential", CREDENTIAL_TYPE],
        "issuer": issuer_did,
        "issuanceDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "credentialSubject": {
            "id": subject_did,
            "home": config.HOME_ID,
            "role": role,
            "permissions": permissions,
        },
    }
    if expires_iso:
        credential["expirationDate"] = expires_iso
    return credential


def remember_issued(
    connection_id: str,
    credential: dict,
    credential_exchange_id: str | None = None,
) -> None:
    """Persist a credential after ACA-Py has accepted the issuance request."""
    initialize_store()
    encoded = json.dumps(credential, separators=(",", ":"), sort_keys=True)
    created_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO issued_credentials (
                    connection_id, credential_exchange_id, credential_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (connection_id, credential_exchange_id, encoded, created_at),
            )


def _grant_scope(credential: dict) -> tuple[str, str, tuple[str, ...]] | None:
    subject = credential.get("credentialSubject")
    if not isinstance(subject, dict):
        return None
    subject_did = subject.get("id")
    role = subject.get("role")
    permissions = subject.get("permissions")
    if (
        not isinstance(subject_did, str)
        or not isinstance(role, str)
        or not isinstance(permissions, list)
        or not all(
            isinstance(permission, str) and permission for permission in permissions
        )
    ):
        return None
    return subject_did, role, tuple(sorted(set(permissions)))


def remember_issued_superseding(
    connection_id: str,
    credential: dict,
    credential_exchange_id: str,
) -> int:
    """Store a grant and atomically revoke older equivalent active grants."""
    target = _grant_scope(credential)
    if (
        not connection_id
        or not credential_exchange_id
        or target is None
        or not _has_expected_scope(credential)
    ):
        raise ValueError("credential does not contain a valid grant scope")

    initialize_store()
    encoded = json.dumps(credential, separators=(",", ":"), sort_keys=True)
    created_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO issued_credentials (
                    connection_id, credential_exchange_id, credential_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (connection_id, credential_exchange_id, encoded, created_at),
            )
            rows = connection.execute(
                """
                SELECT id, credential_json
                FROM issued_credentials
                WHERE connection_id = ?
                  AND id != ?
                  AND revoked_at IS NULL
                ORDER BY id DESC
                """,
                (connection_id, cursor.lastrowid),
            ).fetchall()

            superseded_ids = []
            for record_id, existing_encoded in rows:
                try:
                    existing = json.loads(existing_encoded)
                except (TypeError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(existing, dict)
                    and _grant_scope(existing) == target
                    and _has_expected_scope(existing)
                    and not _is_expired(existing)
                ):
                    superseded_ids.append(record_id)

            if superseded_ids:
                revoked_at = datetime.now(timezone.utc).isoformat()
                connection.executemany(
                    """
                    UPDATE issued_credentials
                    SET revoked_at = COALESCE(revoked_at, ?)
                    WHERE id = ?
                    """,
                    [(revoked_at, record_id) for record_id in superseded_ids],
                )
    return len(superseded_ids)


def _issued_for_connection(connection_id: str) -> list[dict]:
    initialize_store()
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT credential_json
            FROM issued_credentials
            WHERE connection_id = ? AND revoked_at IS NULL
            ORDER BY id DESC
            """,
            (connection_id,),
        ).fetchall()

    issued = []
    for (encoded,) in rows:
        try:
            credential = json.loads(encoded)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(credential, dict):
            issued.append(credential)
    return issued


def revoke_credential(credential_exchange_id: str) -> bool:
    """Revoke one issued credential; return False when it does not exist."""
    if not credential_exchange_id:
        return False
    initialize_store()
    revoked_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE issued_credentials
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE credential_exchange_id = ?
                """,
                (revoked_at, credential_exchange_id),
            )
    return cursor.rowcount > 0


def revoke_connection(connection_id: str) -> bool:
    """Revoke every credential for a connection; return False if none exist."""
    if not connection_id:
        return False
    initialize_store()
    revoked_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE issued_credentials
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE connection_id = ?
                """,
                (revoked_at, connection_id),
            )
    return cursor.rowcount > 0


def list_issued() -> list[dict]:
    """Return sanitized credential records for owner-facing status displays."""
    initialize_store()
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT id, connection_id, credential_exchange_id, credential_json,
                   created_at, revoked_at
            FROM issued_credentials
            ORDER BY id DESC
            """
        ).fetchall()

    records = []
    for (
        record_id,
        connection_id,
        credential_exchange_id,
        encoded,
        created_at,
        revoked_at,
    ) in rows:
        try:
            credential = json.loads(encoded)
        except (TypeError, json.JSONDecodeError):
            credential = {}
        subject = credential.get("credentialSubject", {})
        if not isinstance(subject, dict):
            subject = {}
        permissions = subject.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []
        permissions = [item for item in permissions if isinstance(item, str)]
        credential_types = credential.get("type", [])
        if (
            not isinstance(credential_types, list)
            or CREDENTIAL_TYPE not in credential_types
            or not _has_expected_scope(credential)
        ):
            state = "invalid"
        elif revoked_at:
            state = "revoked"
        elif _is_expired(credential):
            state = "expired"
        else:
            state = "active"
        records.append(
            {
                "id": credential_exchange_id or f"local-{record_id}",
                "credential_exchange_id": credential_exchange_id,
                "connection_id": connection_id,
                "state": state,
                "home_id": subject.get("home")
                if isinstance(subject.get("home"), str)
                else None,
                "issuer_did": credential.get("issuer")
                if isinstance(credential.get("issuer"), str)
                else None,
                "role": subject.get("role")
                if isinstance(subject.get("role"), str)
                else None,
                "subject_did": subject.get("id")
                if isinstance(subject.get("id"), str)
                else None,
                "permissions": permissions,
                "expires_at": credential.get("expirationDate")
                if isinstance(credential.get("expirationDate"), str)
                else None,
                "issued_at": created_at,
                "revoked_at": revoked_at,
            }
        )
    return records


def count_issued_by_state() -> dict[str, int]:
    """Return aggregate credential state counts without exposing identifiers."""
    counts = Counter(record["state"] for record in list_issued())
    return dict(sorted(counts.items()))


def find_equivalent_active_grant(
    connection_id: str,
    subject_did: str,
    role: str,
    permissions: list[str],
) -> dict | None:
    """Return the newest active grant with the same normalized authorization scope."""
    target_permissions = tuple(sorted(set(permissions)))
    for record in list_issued():
        if (
            record["state"] == "active"
            and record["connection_id"] == connection_id
            and record["subject_did"] == subject_did
            and record["role"] == role
            and tuple(sorted(set(record["permissions"]))) == target_permissions
        ):
            return record
    return None


def _is_expired(credential: dict) -> bool:
    expiry = credential.get("expirationDate")
    if not expiry:
        return False
    if not isinstance(expiry, str):
        return True
    try:
        expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Invalid expiry data must never broaden access.
        return True
    if expiry_dt.tzinfo is None:
        return True
    return expiry_dt < datetime.now(timezone.utc)


def _has_expected_scope(credential: dict) -> bool:
    """Require credentials to belong to this gateway's home and issuer."""
    subject = credential.get("credentialSubject")
    return (
        isinstance(subject, dict)
        and subject.get("home") == config.HOME_ID
        and credential.get("issuer") == config.HOME_ISSUER_DID
    )


def is_authorised(connection_id: str, entity_id: str) -> bool:
    """True if a non-expired credential issued to this connection grants entity_id."""
    if not isinstance(connection_id, str) or not isinstance(entity_id, str):
        return False
    for credential in _issued_for_connection(connection_id):
        subject = credential.get("credentialSubject", {})
        if not isinstance(subject, dict):
            continue
        credential_types = credential.get("type", [])
        if (
            not isinstance(credential_types, list)
            or CREDENTIAL_TYPE not in credential_types
        ):
            continue
        if not _has_expected_scope(credential):
            continue
        if _is_expired(credential):
            continue
        permissions = subject.get("permissions", [])
        if not isinstance(permissions, list):
            continue
        if any(
            isinstance(pattern, str) and fnmatch(entity_id, pattern)
            for pattern in permissions
        ):
            return True
    return False


def is_presented_authorised(
    connection_id: str, entity_id: str, presented: dict | None
) -> bool:
    """Authorize the exact presented grant after cryptographic verification.

    A proof of a narrow grant must never unlock a different, broader grant.
    Re-read active records here so revocation during the exchange is enforced.
    """
    if not isinstance(presented, dict):
        return False
    unsigned = {key: value for key, value in presented.items() if key != "proof"}
    subject = unsigned.get("credentialSubject")
    types = unsigned.get("type")
    if (
        not isinstance(subject, dict)
        or not isinstance(types, list)
        or CREDENTIAL_TYPE not in types
        or not _has_expected_scope(unsigned)
        or _is_expired(unsigned)
    ):
        return False
    permissions = subject.get("permissions")
    if not isinstance(permissions, list) or not any(
        isinstance(pattern, str) and fnmatch(entity_id, pattern)
        for pattern in permissions
    ):
        return False
    return any(
        unsigned == {key: value for key, value in stored.items() if key != "proof"}
        for stored in _issued_for_connection(connection_id)
    )


def credential_fingerprint(credential: dict) -> str:
    """Identify an exact issuance payload independently of its added signature."""
    unsigned = {key: value for key, value in credential.items() if key != "proof"}
    return hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()).hexdigest()
