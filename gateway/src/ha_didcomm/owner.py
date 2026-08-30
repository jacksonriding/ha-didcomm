"""Owner operations shared by the HTTP API and command line interface."""
import asyncio

from . import acapy
from . import config
from . import credentials


class EquivalentActiveGrantError(ValueError):
    """Raised when issuance would duplicate an active authorization grant."""


_ISSUANCE_LOCK = asyncio.Lock()


async def issue_access_credential(
    *,
    connection_id: str,
    subject_did: str,
    role: str,
    permissions: list[str],
    expires: str | None = None,
) -> str:
    if not config.HOME_ISSUER_DID:
        raise ValueError("HOME_ISSUER_DID is not configured")
    if not connection_id or not subject_did or not role:
        raise ValueError("connection_id, subject_did, and role are required")
    if not subject_did.startswith("did:key:") or any(
        character.isspace() for character in subject_did
    ):
        raise ValueError("subject_did must be a did:key identity")
    if not permissions or not all(
        isinstance(permission, str) and permission for permission in permissions
    ):
        raise ValueError("at least one non-empty permission is required")

    credential = credentials.build_credential(
        subject_did=subject_did,
        issuer_did=config.HOME_ISSUER_DID,
        role=role,
        permissions=permissions,
        expires_iso=expires,
    )
    async with _ISSUANCE_LOCK:
        if credentials.find_equivalent_active_grant(
            connection_id, subject_did, role, permissions
        ):
            raise EquivalentActiveGrantError
        result = await acapy.issue_credential(connection_id, credential)
        credential_exchange_id = result.get("cred_ex_id")
        if not isinstance(credential_exchange_id, str) or not credential_exchange_id:
            raise ValueError("ACA-Py response did not contain a cred_ex_id")
        credentials.remember_issued_superseding(
            connection_id, credential, credential_exchange_id
        )
    return credential_exchange_id
