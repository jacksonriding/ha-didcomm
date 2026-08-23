"""Constants for the ha-didcomm integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "ha_didcomm"
CONF_URL = "url"
CONF_OWNER_API_TOKEN = "owner_api_token"
DEFAULT_URL = "https://homeassistant.local:8000"
PLATFORMS = [Platform.SENSOR]
UPDATE_INTERVAL = timedelta(seconds=30)

SERVICE_CREATE_INVITATION = "create_invitation"
SERVICE_ISSUE_CREDENTIAL = "issue_credential"
SERVICE_REVOKE_CREDENTIAL = "revoke_credential"
SERVICE_REVOKE_CONNECTION = "revoke_connection"
