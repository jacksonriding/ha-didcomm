"""Client for the ha-didcomm read-only status API."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession


class GatewayApiError(Exception):
    """Raised when gateway status cannot be loaded or validated."""


class GatewayClient:
    """Small asynchronous client backed by Home Assistant's shared session."""

    def __init__(self, base_url: str, session: ClientSession) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session

    async def async_get_status(self) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self.base_url}/status", timeout=10
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (ClientError, TimeoutError, ValueError) as error:
            raise GatewayApiError("Unable to load gateway status") from error

        if not isinstance(payload, dict):
            raise GatewayApiError("Gateway returned an invalid response")
        if not isinstance(payload.get("instance_id"), str):
            raise GatewayApiError("Gateway response has no instance identifier")
        for key in ("connections", "credentials"):
            records = payload.get(key)
            if not isinstance(records, list) or not all(
                isinstance(record, dict) and isinstance(record.get("id"), str)
                for record in records
            ):
                raise GatewayApiError(f"Gateway response has invalid {key}")
        return payload
