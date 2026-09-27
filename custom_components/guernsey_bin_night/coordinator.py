"""Shared schedule updates for all sensors at one address."""

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BinNightClient, BinNightError, Schedule, parse_schedule
from .const import (
    CONF_ADDRESS_ID,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class BinNightCoordinator(DataUpdateCoordinator[Schedule]):
    """Fetch one schedule for all sensors, every 24 hours by default."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: BinNightClient
    ) -> None:
        self._normal_interval = timedelta(
            hours=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=self._normal_interval,
            # Refresh metadata changes even when the collection dates do not.
            always_update=True,
        )
        self.client = client
        self.address_id = entry.data[CONF_ADDRESS_ID]
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.last_successful_update: datetime | None = None
        self.data_stale = True
        self._refresh_failed = False
        self._retry_interval: timedelta | None = None

    async def _async_setup(self) -> None:
        """Restore a validated schedule before attempting the first request."""
        try:
            cached = await self.store.async_load()
            if cached is None:
                return
            updated = dt_util.parse_datetime(cached["last_successful_update"])
            if updated is None or updated.tzinfo is None:
                raise ValueError("Invalid cache timestamp")
            schedule = parse_schedule(cached["schedule"], self.address_id)
        except (
            OSError,
            HomeAssistantError,
            BinNightError,
            KeyError,
            TypeError,
            ValueError,
        ):
            _LOGGER.warning("Unable to restore the saved bin schedule; fetching anew")
            return
        self.data = schedule
        self.last_successful_update = updated

    async def _async_update_data(self) -> Schedule:
        try:
            schedule = await self.client.schedule(self.address_id)
        except BinNightError as err:
            self.data_stale = True
            # Use the coordinator's existing timer; do not add a retry task per sensor.
            self._retry_interval = min(
                self._retry_interval * 2
                if self._retry_interval is not None
                else timedelta(minutes=15),
                timedelta(hours=6),
                self._normal_interval,
            )
            self.update_interval = self._retry_interval
            if self.last_successful_update is not None:
                if not self._refresh_failed:
                    _LOGGER.warning(
                        "Collection service refresh failed; retaining saved bin dates"
                    )
                self._refresh_failed = True
                return self.data
            raise UpdateFailed(str(err)) from err
        if self._refresh_failed:
            _LOGGER.info("Collection service refresh recovered")
        self._refresh_failed = False
        self._retry_interval = None
        self.update_interval = self._normal_interval
        self.data_stale = False
        self.last_successful_update = dt_util.utcnow()
        try:
            await self.store.async_save(
                {
                    "last_successful_update": self.last_successful_update.isoformat(),
                    "schedule": {
                        "addressid": schedule.address.id,
                        "address": schedule.address.name,
                        "services": {
                            key: {
                                "name": name,
                                "imageurl": schedule.service_images.get(key),
                            }
                            for key, name in schedule.services.items()
                        },
                        "servicedates": {
                            item.date.isoformat(): {"services": list(item.service_ids)}
                            for item in schedule.collections
                        },
                    },
                }
            )
        except (OSError, HomeAssistantError):
            _LOGGER.warning("Unable to save bin dates for use after a restart")
        return schedule
