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
