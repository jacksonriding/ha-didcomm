"""Client for the ha-didcomm read-only status API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession


class GatewayApiError(Exception):
    """Raised when gateway status cannot be loaded or validated."""


class GatewayAuthError(GatewayApiError):
    """Raised when the owner token is rejected."""


class GatewayOwnerNotConfiguredError(GatewayApiError):
    """Raised when the gateway owner API is disabled."""


class GatewayNotFoundError(GatewayApiError):
    """Raised when an owner mutation target does not exist."""


class GatewayConflictError(GatewayApiError):
    """Raised when an owner mutation conflicts with active gateway state."""


class GatewayClient:
    """Small asynchronous client backed by Home Assistant's shared session."""

    def __init__(
        self,
        base_url: str,
        session: ClientSession,
        owner_api_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._owner_api_token = owner_api_token

    async def async_get_status(self) -> dict[str, Any]:
        path = "/owner/status" if self._owner_api_token else "/status"
        headers = (
            {"Authorization": f"Bearer {self._owner_api_token}"}
            if self._owner_api_token
            else None
        )
        try:
            async with self._session.get(
                f"{self.base_url}{path}", headers=headers, timeout=10
            ) as response:
                if response.status == 401:
                    raise GatewayAuthError("The gateway rejected the owner token")
                if response.status == 503:
                    try:
                        detail = (await response.json()).get("detail")
                    except (ValueError, AttributeError):
                        detail = None
                    if detail == "Owner API is not configured":
                        raise GatewayOwnerNotConfiguredError(
                            "The gateway owner API is not configured"
                        )
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

    async def _async_owner_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._owner_api_token:
            raise GatewayOwnerNotConfiguredError(
                "Owner authentication is not configured"
            )
        try:
            async with self._session.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._owner_api_token}"},
                timeout=10,
            ) as response:
                if response.status == 401:
                    raise GatewayAuthError("The gateway rejected the owner token")
                if response.status == 404:
                    raise GatewayNotFoundError(
                        "The requested gateway record was not found"
                    )
                if response.status == 409:
                    raise GatewayConflictError(
                        "An equivalent active gateway grant already exists"
                    )
                if response.status == 503:
                    try:
                        detail = (await response.json()).get("detail")
                    except (ValueError, AttributeError):
                        detail = None
                    if detail == "Owner API is not configured":
                        raise GatewayOwnerNotConfiguredError(
                            "The gateway owner API is not configured"
                        )
                    raise GatewayApiError("The gateway owner operation is unavailable")
                response.raise_for_status()
                result = await response.json()
        except GatewayApiError:
            raise
        except (ClientError, TimeoutError, ValueError) as error:
            raise GatewayApiError("Unable to complete the owner operation") from error
        if not isinstance(result, dict):
            raise GatewayApiError("Gateway returned an invalid owner response")
        return result

    async def async_validate_owner(self) -> None:
        result = await self._async_owner_request("GET", "/owner/health")
        if result.get("status") != "ok":
            raise GatewayApiError("Gateway returned an invalid owner health response")

    async def async_create_invitation(self, label: str | None = None) -> dict[str, Any]:
        payload = {"label": label} if label else {}
        result = await self._async_owner_request("POST", "/owner/invitations", payload)
        if not isinstance(result.get("invitation_url"), str):
            raise GatewayApiError("Gateway returned an invalid invitation response")
        return result

    async def async_issue_credential(
        self,
        *,
        connection_id: str,
        subject_did: str,
        permissions: list[str],
        role: str,
        duration_hours: int,
    ) -> dict[str, Any]:
        result = await self._async_owner_request(
            "POST",
            "/owner/credentials",
            {
                "connection_id": connection_id,
                "subject_did": subject_did,
                "permissions": permissions,
                "role": role,
                "duration_hours": duration_hours,
            },
        )
        if not isinstance(result.get("cred_ex_id"), str) or not isinstance(
            result.get("expires_at"), str
        ):
            raise GatewayApiError("Gateway returned an invalid issuance response")
        return result

    async def async_revoke_credential(self, credential_exchange_id: str) -> None:
        encoded_id = quote(credential_exchange_id, safe="")
        await self._async_owner_request(
            "POST", f"/owner/credentials/{encoded_id}/revoke", {}
        )

    async def async_revoke_connection(self, connection_id: str) -> None:
        encoded_id = quote(connection_id, safe="")
        await self._async_owner_request(
            "POST", f"/owner/connections/{encoded_id}/revoke", {}
        )
