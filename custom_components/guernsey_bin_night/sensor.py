"""Next bin night and per-service date sensors."""

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import BinNightConfigEntry
from .const import BASE_URL, DOMAIN
from .coordinator import BinNightCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BinNightConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors, including new services added by the collection service later."""
    coordinator = entry.runtime_data
    known_services: set[str] = set()
    async_add_entities([BinNightSensor(coordinator, None)])

    @callback
    def add_services() -> None:
        new_services = coordinator.data.services.keys() - known_services
        if new_services:
            async_add_entities(
                BinNightSensor(coordinator, key) for key in sorted(new_services)
            )
            known_services.update(new_services)

    add_services()
    entry.async_on_unload(coordinator.async_add_listener(add_services))

    @callback
    def midnight_refresh(now: datetime) -> None:
        # Recalculate dates even if no API response has changed since yesterday.
        coordinator.async_update_listeners()

    entry.async_on_unload(
        async_track_time_change(hass, midnight_refresh, hour=0, minute=0, second=0)
    )


class BinNightSensor(CoordinatorEntity[BinNightCoordinator], SensorEntity):
    """A date sensor backed by the shared address schedule."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_has_entity_name = True
    _attr_icon = "mdi:trash-can-outline"

    def __init__(
        self,
        coordinator: BinNightCoordinator,
        service_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._service_id = service_id
        self._attr_unique_id = (
            f"{coordinator.address_id}_{service_id or 'next_collection'}"
        )
        if service_id is None:
            self._attr_translation_key = "next_collection"
        else:
            self._attr_name = coordinator.data.services[service_id]
            self._attr_icon = "mdi:recycle"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address_id)},
            name="Bin collections",
            manufacturer="States of Guernsey",
            model="Bin collections",
            configuration_url="https://www.gov.gg/mybinnight",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def entity_picture(self) -> str | None:
        """Expose the material image using HA's native attribute."""
        path = self.coordinator.data.service_images.get(self._service_id)
        return f"{BASE_URL}{path}" if path else None

    @property
    def native_value(self) -> date | None:
        """Keep today's collection until local midnight."""
        collection = self.coordinator.data.next_collection(
            dt_util.now().date(), self._service_id
        )
        return collection.date if collection else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose stable values suitable for reminders and dashboards."""
        today = dt_util.now().date()
        schedule = self.coordinator.data
        collection = schedule.next_collection(today, self._service_id)
        attributes: dict[str, Any] = {
            "days_until": (collection.date - today).days if collection else None,
            "last_successful_update": self.coordinator.last_successful_update,
            "data_stale": self.coordinator.data_stale,
        }
        if self._service_id is None:
            attributes["collections"] = (
                [schedule.services[key] for key in collection.service_ids]
                if collection
                else []
            )
        else:
            attributes["service_id"] = self._service_id
        return attributes
