"""Config flow for ha-didcomm."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import GatewayApiError, GatewayAuthError, GatewayClient
from .const import CONF_OWNER_API_TOKEN, CONF_URL, DEFAULT_URL, DOMAIN


async def _validate_gateway(
    hass: HomeAssistant, url: str, owner_api_token: str
) -> dict[str, Any]:
    client = GatewayClient(url, async_get_clientsession(hass), owner_api_token)
    status = await client.async_get_status()
    await client.async_validate_owner()
    return status


def _schema(default_url: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=default_url): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
            vol.Required(CONF_OWNER_API_TOKEN, default=""): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


class HaDidcommConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local ha-didcomm gateway."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            owner_api_token = user_input[CONF_OWNER_API_TOKEN].strip()
            try:
                status = await _validate_gateway(self.hass, url, owner_api_token)
            except GatewayAuthError:
                errors["base"] = "invalid_auth"
            except GatewayApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(status["instance_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=status.get("home_id") or "ha-didcomm",
                    data={
                        CONF_URL: url,
                        CONF_OWNER_API_TOKEN: owner_api_token,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=_schema(DEFAULT_URL), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None):
        """Allow the status API URL to be changed without removing entities."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            owner_api_token = user_input[
                CONF_OWNER_API_TOKEN
            ].strip() or entry.data.get(CONF_OWNER_API_TOKEN, "")
            try:
                status = await _validate_gateway(self.hass, url, owner_api_token)
            except GatewayAuthError:
                errors["base"] = "invalid_auth"
            except GatewayApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(status["instance_id"])
                self._abort_if_unique_id_mismatch(reason="wrong_gateway")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_URL: url,
                        CONF_OWNER_API_TOKEN: owner_api_token,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(entry.data[CONF_URL]),
            errors=errors,
        )
