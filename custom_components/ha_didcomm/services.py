"""Admin-only Home Assistant actions for gateway ownership."""

from __future__ import annotations

from functools import partial

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api import (
    GatewayApiError,
    GatewayAuthError,
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayOwnerNotConfiguredError,
)
from .const import (
    CONF_OWNER_API_TOKEN,
    DOMAIN,
    SERVICE_CREATE_INVITATION,
    SERVICE_ISSUE_CREDENTIAL,
    SERVICE_REVOKE_CONNECTION,
    SERVICE_REVOKE_CREDENTIAL,
)
from .coordinator import HaDidcommCoordinator

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CONNECTION_ID = "connection_id"
ATTR_CREDENTIAL_EXCHANGE_ID = "credential_exchange_id"
ATTR_DURATION_HOURS = "duration_hours"
ATTR_LABEL = "label"
ATTR_PERMISSIONS = "permissions"
ATTR_ROLE = "role"
ATTR_SUBJECT_DID = "subject_did"

ENTRY_SCHEMA = {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}
CREATE_INVITATION_SCHEMA = vol.Schema(
    {**ENTRY_SCHEMA, vol.Optional(ATTR_LABEL): cv.string}
)
ISSUE_CREDENTIAL_SCHEMA = vol.Schema(
    {
        **ENTRY_SCHEMA,
        vol.Required(ATTR_CONNECTION_ID): cv.string,
        vol.Required(ATTR_SUBJECT_DID): cv.string,
        vol.Required(ATTR_PERMISSIONS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_ROLE, default="guest"): cv.string,
        vol.Required(ATTR_DURATION_HOURS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=8760)
        ),
    }
)
REVOKE_CREDENTIAL_SCHEMA = vol.Schema(
    {**ENTRY_SCHEMA, vol.Required(ATTR_CREDENTIAL_EXCHANGE_ID): cv.string}
)
REVOKE_CONNECTION_SCHEMA = vol.Schema(
    {**ENTRY_SCHEMA, vol.Required(ATTR_CONNECTION_ID): cv.string}
)


def _coordinator_for_call(
    hass: HomeAssistant, call: ServiceCall
) -> HaDidcommCoordinator:
    entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_unavailable",
        )
    if not entry.data.get(CONF_OWNER_API_TOKEN):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="owner_not_configured",
        )
    return entry.runtime_data


def _raise_action_error(error: GatewayApiError) -> None:
    if isinstance(error, GatewayAuthError):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_owner_token"
        ) from error
    if isinstance(error, GatewayOwnerNotConfiguredError):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="owner_not_configured"
        ) from error
    if isinstance(error, GatewayNotFoundError):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="record_not_found"
        ) from error
    if isinstance(error, GatewayConflictError):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="active_grant_exists"
        ) from error
    raise HomeAssistantError(
        translation_domain=DOMAIN, translation_key="owner_operation_failed"
    ) from error


async def _create_invitation(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse | None:
    coordinator = _coordinator_for_call(hass, call)
    try:
        result = await coordinator.client.async_create_invitation(
            call.data.get(ATTR_LABEL)
        )
        await coordinator.async_request_refresh()
        return result if call.return_response else None
    except GatewayApiError as error:
        _raise_action_error(error)


async def _issue_credential(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse | None:
    if not call.data[ATTR_PERMISSIONS] or not all(
        permission.strip() for permission in call.data[ATTR_PERMISSIONS]
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_permissions"
        )
    coordinator = _coordinator_for_call(hass, call)
    try:
        result = await coordinator.client.async_issue_credential(
            connection_id=call.data[ATTR_CONNECTION_ID],
            subject_did=call.data[ATTR_SUBJECT_DID],
            permissions=call.data[ATTR_PERMISSIONS],
            role=call.data[ATTR_ROLE],
            duration_hours=call.data[ATTR_DURATION_HOURS],
        )
        await coordinator.async_request_refresh()
        return result if call.return_response else None
    except GatewayApiError as error:
        _raise_action_error(error)


async def _revoke_credential(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _coordinator_for_call(hass, call)
    try:
        await coordinator.client.async_revoke_credential(
            call.data[ATTR_CREDENTIAL_EXCHANGE_ID]
        )
        await coordinator.async_request_refresh()
    except GatewayApiError as error:
        _raise_action_error(error)


async def _revoke_connection(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _coordinator_for_call(hass, call)
    try:
        await coordinator.client.async_revoke_connection(call.data[ATTR_CONNECTION_ID])
        await coordinator.async_request_refresh()
    except GatewayApiError as error:
        _raise_action_error(error)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register global owner actions with Home Assistant admin enforcement."""
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_CREATE_INVITATION,
        partial(_create_invitation, hass),
        CREATE_INVITATION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_ISSUE_CREDENTIAL,
        partial(_issue_credential, hass),
        ISSUE_CREDENTIAL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_REVOKE_CREDENTIAL,
        partial(_revoke_credential, hass),
        REVOKE_CREDENTIAL_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_REVOKE_CONNECTION,
        partial(_revoke_connection, hass),
        REVOKE_CONNECTION_SCHEMA,
    )
