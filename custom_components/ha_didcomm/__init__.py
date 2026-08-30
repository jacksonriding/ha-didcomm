"""Home Assistant integration for ha-didcomm."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import GatewayClient
from .const import CONF_OWNER_API_TOKEN, CONF_URL, PLATFORMS
from .coordinator import HaDidcommCoordinator
from .services import async_setup_services


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up global ha-didcomm actions."""
    async_setup_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep version-one entries summary-only until an owner token is added."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha-didcomm from a config entry."""
    client = GatewayClient(
        entry.data[CONF_URL],
        async_get_clientsession(hass),
        entry.data.get(CONF_OWNER_API_TOKEN),
    )
    coordinator = HaDidcommCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a ha-didcomm config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
