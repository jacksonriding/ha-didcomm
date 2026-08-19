"""Home Assistant integration for ha-didcomm."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GatewayClient
from .const import CONF_URL, PLATFORMS
from .coordinator import HaDidcommCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha-didcomm from a config entry."""
    client = GatewayClient(entry.data[CONF_URL], async_get_clientsession(hass))
    coordinator = HaDidcommCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a ha-didcomm config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
