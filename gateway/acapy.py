"""Thin client for the parts of the ACA-Py Admin API the gateway needs."""
import httpx

import config


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if config.ACAPY_ADMIN_API_KEY:
        headers["X-API-Key"] = config.ACAPY_ADMIN_API_KEY
    return headers


async def send_basic_message(connection_id: str, content: str) -> None:
    """Send a DIDComm Basic Message to an established connection."""
    url = f"{config.ACAPY_ADMIN_URL}/connections/{connection_id}/send-message"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={"content": content}, headers=_headers())
        response.raise_for_status()


async def create_oob_invitation(
    *,
    label: str | None = None,
    multi_use: bool = False,
    auto_accept: bool = True,
) -> dict:
    """Create a ledger-free DID Exchange invitation using did:peer:4."""
    url = f"{config.ACAPY_ADMIN_URL}/out-of-band/create-invitation"
    body = {
        "handshake_protocols": ["https://didcomm.org/didexchange/1.1"],
        "protocol_version": "1.1",
        "use_did_method": "did:peer:4",
    }
    if label:
        body["my_label"] = label
    params = {
        "auto_accept": str(auto_accept).lower(),
        "multi_use": str(multi_use).lower(),
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, params=params, headers=_headers())
        response.raise_for_status()
        invitation = response.json()
    if not isinstance(invitation.get("invitation_url"), str):
        raise ValueError("ACA-Py response did not contain an invitation_url")
    return invitation


async def issue_credential(connection_id: str, credential: dict) -> dict:
    """Issue a JSON-LD verifiable credential (no ledger/schema registration needed)."""
    url = f"{config.ACAPY_ADMIN_URL}/issue-credential-2.0/send"
    body = {
        "connection_id": connection_id,
        "filter": {
            "ld_proof": {
                "credential": credential,
                "options": {"proofType": "Ed25519Signature2018"},
            }
        },
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, headers=_headers())
        response.raise_for_status()
        return response.json()
