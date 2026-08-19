"""Connection and credential entities for ha-didcomm."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HaDidcommCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up and dynamically add connection and credential sensors."""
    coordinator: HaDidcommCoordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[SensorEntity] = []
        for connection in coordinator.data["connections"]:
            key = ("connection", connection["id"])
            if key not in known:
                known.add(key)
                entities.append(ConnectionSensor(coordinator, entry, connection["id"]))
        for credential in coordinator.data["credentials"]:
            key = ("credential", credential["id"])
            if key not in known:
                known.add(key)
                entities.append(CredentialSensor(coordinator, entry, credential["id"]))
        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class HaDidcommEntity(CoordinatorEntity[HaDidcommCoordinator], SensorEntity):
    """Base class for status-backed entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HaDidcommCoordinator,
        entry: ConfigEntry,
        record_id: str,
        collection: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._record_id = record_id
        self._collection = collection

    @property
    def record(self) -> dict[str, Any] | None:
        return next(
            (
                record
                for record in self.coordinator.data[self._collection]
                if record["id"] == self._record_id
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.record is not None


class ConnectionSensor(HaDidcommEntity):
    """Represent one ACA-Py connection."""

    _attr_name = None

    def __init__(
        self,
        coordinator: HaDidcommCoordinator,
        entry: ConfigEntry,
        connection_id: str,
    ) -> None:
        super().__init__(coordinator, entry, connection_id, "connections")
        self._attr_unique_id = (
            f"{coordinator.data['instance_id']}_connection_{connection_id}"
        )

    @property
    def native_value(self) -> str | None:
        return self.record.get("state") if self.record else None

    @property
    def device_info(self) -> DeviceInfo:
        record = self.record or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=record.get("label") or f"DIDComm {self._record_id[:8]}",
            manufacturer="ha-didcomm",
            model="DIDComm connection",
            configuration_url=self._entry.data["url"],
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self.record or {}
        return {
            "connection_id": self._record_id,
            "their_did": record.get("their_did"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        }


class CredentialSensor(HaDidcommEntity):
    """Represent one issued access credential."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["active", "expired", "revoked", "invalid"]
    _attr_translation_key = "credential"

    def __init__(
        self,
        coordinator: HaDidcommCoordinator,
        entry: ConfigEntry,
        credential_id: str,
    ) -> None:
        super().__init__(coordinator, entry, credential_id, "credentials")
        self._attr_unique_id = (
            f"{coordinator.data['instance_id']}_credential_{credential_id}"
        )
        self._attr_translation_placeholders = {"credential_id": credential_id[:8]}

    @property
    def native_value(self) -> str | None:
        return self.record.get("state") if self.record else None

    @property
    def device_info(self) -> DeviceInfo | None:
        record = self.record
        if not record:
            return None
        connection_id = record.get("connection_id")
        if not any(
            connection.get("id") == connection_id
            for connection in self.coordinator.data["connections"]
        ):
            return None
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self.coordinator.data['instance_id']}_connection_"
                    f"{connection_id}",
                )
            }
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self.record or {}
        return {
            "credential_exchange_id": record.get("credential_exchange_id"),
            "connection_id": record.get("connection_id"),
            "role": record.get("role"),
            "subject_did": record.get("subject_did"),
            "permissions": record.get("permissions", []),
            "issued_at": record.get("issued_at"),
            "expires_at": record.get("expires_at"),
            "revoked_at": record.get("revoked_at"),
        }
