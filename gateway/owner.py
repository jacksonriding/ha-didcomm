"""Owner operations shared by the HTTP API and command line interface."""
import acapy
import config
import credentials


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
    result = await acapy.issue_credential(connection_id, credential)
    credential_exchange_id = result.get("cred_ex_id")
    if not isinstance(credential_exchange_id, str) or not credential_exchange_id:
        raise ValueError("ACA-Py response did not contain a cred_ex_id")
    credentials.remember_issued(
        connection_id, credential, credential_exchange_id
    )
    return credential_exchange_id
