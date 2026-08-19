"""Constants for the ha-didcomm integration."""
from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "ha_didcomm"
CONF_URL = "url"
DEFAULT_URL = "http://homeassistant.local:8090"
PLATFORMS = [Platform.SENSOR]
UPDATE_INTERVAL = timedelta(seconds=30)
