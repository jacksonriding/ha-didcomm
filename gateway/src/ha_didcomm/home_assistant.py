"""Thin client for the Home Assistant REST API."""
import httpx

from . import config


async def call_service(domain: str, service: str, entity_id: str) -> None:
    """Call a Home Assistant service, e.g. call_service("light", "turn_on", "light.office")."""
    url = f"{config.HA_BASE_URL}/api/services/{domain}/{service}"
    headers = {
        "Authorization": f"Bearer {config.HA_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={"entity_id": entity_id}, headers=headers)
        response.raise_for_status()
