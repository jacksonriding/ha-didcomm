"""Verifiable-credential based authorization (v0.0.3).

Replaces the v0.0.2 static config/policies.yaml allowlist with real W3C
verifiable credentials (JSON-LD, ld_proof), issued to a connection via
ACA-Py's Issue Credential 2.0 protocol.

Note on scope: this checks the credentials the home has issued to a
connection (in-memory, per gateway process) rather than running a live
Present Proof exchange asking the remote party to prove current possession.
A first attempt at wiring up DIF Presentation Exchange proof-of-possession
hit an ACA-Py bug in this version -- its DIF/LD-proof handler ignores the
explicit issuer_id passed to /present-proof-2.0/records/{id}/send-presentation
(it always re-derives the signing DID itself via is_holder_override=True,
and that derivation doesn't reliably resolve did:key credential subjects).
Live possession proof is deferred; see ROADMAP.md.

Credentials use JSON-LD (ld_proof) so no ledger/schema registration is
needed: the @context is defined inline, and DIDs are did:key identities
(issuer = the home's did:key, subject = the remote party's did:key).
"""
from datetime import datetime, timezone
from fnmatch import fnmatch

import config

CREDENTIAL_TYPE = "SmartHomeAccessCredential"

# connection_id -> list of issued credential dicts (in-memory; cleared on
# gateway restart -- a real deployment would persist this).
ISSUED: dict[str, list[dict]] = {}


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


def remember_issued(connection_id: str, credential: dict) -> None:
    ISSUED.setdefault(connection_id, []).append(credential)


def _is_expired(credential: dict) -> bool:
    expiry = credential.get("expirationDate")
    if not expiry:
        return False
    try:
        expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expiry_dt < datetime.now(timezone.utc)


def is_authorised(connection_id: str, entity_id: str) -> bool:
    """True if a non-expired credential issued to this connection grants entity_id."""
    for credential in ISSUED.get(connection_id, []):
        subject = credential.get("credentialSubject", {})
        if CREDENTIAL_TYPE not in credential.get("type", []):
            continue
        if subject.get("home") != config.HOME_ID:
            continue
        if _is_expired(credential):
            continue
        permissions = subject.get("permissions", [])
        if any(fnmatch(entity_id, pattern) for pattern in permissions):
            return True
    return False
