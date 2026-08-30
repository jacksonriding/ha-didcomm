"""Tests for the Home Assistant gateway client."""

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.ha_didcomm.api import (
    GatewayAuthError,
    GatewayClient,
    GatewayConflictError,
    GatewayNotFoundError,
)


async def test_owner_client_sends_bearer_to_owner_status_routes(hass, aioclient_mock):
    base_url = "https://ha.example:8443"
    status = {
        "instance_id": "did:key:home",
        "connections": [],
        "credentials": [],
    }
    aioclient_mock.get(f"{base_url}/owner/status", json=status)
    aioclient_mock.get(f"{base_url}/owner/health", json={"status": "ok"})
    client = GatewayClient(base_url, async_get_clientsession(hass), "a" * 40)

    assert await client.async_get_status() == status
    await client.async_validate_owner()

    status_request = aioclient_mock.mock_calls[0]
    owner_request = aioclient_mock.mock_calls[1]
    assert status_request[3]["Authorization"] == f"Bearer {'a' * 40}"
    assert owner_request[3]["Authorization"] == f"Bearer {'a' * 40}"


async def test_client_can_read_public_summary_without_owner_token(hass, aioclient_mock):
    base_url = "https://ha.example:8443"
    status = {
        "instance_id": "did:key:home",
        "connections": [],
        "credentials": [],
    }
    aioclient_mock.get(f"{base_url}/status", json=status)
    client = GatewayClient(base_url, async_get_clientsession(hass))

    assert await client.async_get_status() == status


async def test_owner_client_maps_auth_and_not_found(hass, aioclient_mock):
    base_url = "https://ha.example:8443"
    client = GatewayClient(base_url, async_get_clientsession(hass), "a" * 40)
    aioclient_mock.get(f"{base_url}/owner/health", status=401)
    aioclient_mock.post(f"{base_url}/owner/credentials/missing/revoke", status=404)

    with pytest.raises(GatewayAuthError):
        await client.async_validate_owner()
    with pytest.raises(GatewayNotFoundError):
        await client.async_revoke_credential("missing")


async def test_owner_client_maps_duplicate_grant_conflict(hass, aioclient_mock):
    base_url = "https://ha.example:8443"
    client = GatewayClient(base_url, async_get_clientsession(hass), "a" * 40)
    aioclient_mock.post(f"{base_url}/owner/credentials", status=409)

    with pytest.raises(GatewayConflictError):
        await client.async_issue_credential(
            connection_id="connection-1",
            subject_did="did:key:guest",
            permissions=["light.*"],
            role="guest",
            duration_hours=24,
        )
