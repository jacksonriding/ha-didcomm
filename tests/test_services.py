"""Tests for admin-only owner actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers.service import async_get_all_descriptions
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_didcomm.const import (
    CONF_OWNER_API_TOKEN,
    CONF_URL,
    DOMAIN,
    SERVICE_CREATE_INVITATION,
    SERVICE_ISSUE_CREDENTIAL,
    SERVICE_REVOKE_CONNECTION,
    SERVICE_REVOKE_CREDENTIAL,
)
from custom_components.ha_didcomm.services import async_setup_services


def loaded_entry(hass, *, token: str | None = "a" * 40):
    data = {CONF_URL: "https://ha.example:8443"}
    if token is not None:
        data[CONF_OWNER_API_TOKEN] = token
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=2)
    entry.add_to_hass(hass)
    client = SimpleNamespace(
        async_create_invitation=AsyncMock(
            return_value={"invitation_url": "https://example.test/oob"}
        ),
        async_issue_credential=AsyncMock(
            return_value={
                "cred_ex_id": "exchange-1",
                "expires_at": "2099-01-01T00:00:00Z",
            }
        ),
        async_revoke_credential=AsyncMock(),
        async_revoke_connection=AsyncMock(),
    )
    coordinator = SimpleNamespace(
        client=client,
        async_request_refresh=AsyncMock(),
    )
    entry.runtime_data = coordinator
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry, coordinator


async def test_actions_return_data_and_refresh(hass):
    entry, coordinator = loaded_entry(hass)
    async_setup_services(hass)

    invitation = await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE_INVITATION,
        {"config_entry_id": entry.entry_id, "label": "Guest"},
        blocking=True,
        return_response=True,
    )
    issued = await hass.services.async_call(
        DOMAIN,
        SERVICE_ISSUE_CREDENTIAL,
        {
            "config_entry_id": entry.entry_id,
            "connection_id": "connection-1",
            "subject_did": "did:key:guest",
            "permissions": ["light.guest_*"],
            "role": "guest",
            "duration_hours": 24,
        },
        blocking=True,
        return_response=True,
    )

    assert invitation == {"invitation_url": "https://example.test/oob"}
    assert issued["cred_ex_id"] == "exchange-1"
    assert coordinator.async_request_refresh.await_count == 2


async def test_revocation_actions_refresh(hass):
    entry, coordinator = loaded_entry(hass)
    async_setup_services(hass)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REVOKE_CREDENTIAL,
        {
            "config_entry_id": entry.entry_id,
            "credential_exchange_id": "exchange-1",
        },
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_REVOKE_CONNECTION,
        {"config_entry_id": entry.entry_id, "connection_id": "connection-1"},
        blocking=True,
    )

    coordinator.client.async_revoke_credential.assert_awaited_once_with("exchange-1")
    coordinator.client.async_revoke_connection.assert_awaited_once_with("connection-1")
    assert coordinator.async_request_refresh.await_count == 2


async def test_read_only_entry_gets_configuration_error(hass):
    entry, _ = loaded_entry(hass, token=None)
    async_setup_services(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CREATE_INVITATION,
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )


async def test_non_admin_cannot_call_owner_action(hass):
    entry, _ = loaded_entry(hass)
    async_setup_services(hass)
    await hass.auth.async_create_user("Owner")
    user = await hass.auth.async_create_user("Guest")

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CREATE_INVITATION,
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
            context=Context(user_id=user.id),
        )


async def test_action_descriptions_load(hass):
    async_setup_services(hass)

    descriptions = await async_get_all_descriptions(hass)

    assert (
        "config_entry_id" in descriptions[DOMAIN][SERVICE_CREATE_INVITATION]["fields"]
    )
    assert descriptions[DOMAIN][SERVICE_CREATE_INVITATION]["response"] == {
        "optional": True
    }
