"""Tests for ha-didcomm configuration and migration."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_didcomm import async_migrate_entry
from custom_components.ha_didcomm.api import GatewayAuthError
from custom_components.ha_didcomm.const import (
    CONF_OWNER_API_TOKEN,
    CONF_URL,
    DOMAIN,
)

STATUS = {
    "instance_id": "did:key:home",
    "home_id": "My home",
    "connections": [],
    "credentials": [],
}


async def test_new_setup_validates_status_and_owner(hass):
    with patch(
        "custom_components.ha_didcomm.config_flow._validate_gateway",
        AsyncMock(return_value=STATUS),
    ) as validate:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_URL: "https://ha.example:8443/",
                CONF_OWNER_API_TOKEN: "a" * 40,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_URL: "https://ha.example:8443",
        CONF_OWNER_API_TOKEN: "a" * 40,
    }
    validate.assert_awaited_once_with(hass, "https://ha.example:8443", "a" * 40)


async def test_version_one_entry_migrates_read_only(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "https://ha.example:8443"},
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert CONF_OWNER_API_TOKEN not in entry.data


async def test_reconfigure_adds_owner_token_without_replacing_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="did:key:home",
        data={CONF_URL: "https://old.example:8443"},
        version=2,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.ha_didcomm.config_flow._validate_gateway",
        AsyncMock(return_value=STATUS),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
            data={
                CONF_URL: "https://new.example:8443",
                CONF_OWNER_API_TOKEN: "b" * 40,
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_URL] == "https://new.example:8443"
    assert entry.data[CONF_OWNER_API_TOKEN] == "b" * 40


async def test_setup_reports_rejected_owner_token(hass):
    with patch(
        "custom_components.ha_didcomm.config_flow._validate_gateway",
        AsyncMock(side_effect=GatewayAuthError("rejected")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_URL: "https://ha.example:8443",
                CONF_OWNER_API_TOKEN: "bad" * 20,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
