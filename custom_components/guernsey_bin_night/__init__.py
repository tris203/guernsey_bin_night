"""Guernsey Bin Night integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import BinNightClient
from .const import DOMAIN
from .coordinator import BinNightCoordinator

type BinNightConfigEntry = ConfigEntry[BinNightCoordinator]

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: BinNightConfigEntry) -> bool:
    """Set up a selected address, retrying automatically on connection failure."""
    coordinator = BinNightCoordinator(
        hass, entry, BinNightClient(async_get_clientsession(hass))
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def _async_update_options(
    hass: HomeAssistant, entry: BinNightConfigEntry
) -> None:
    """Apply a changed polling interval."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BinNightConfigEntry) -> bool:
    """Unload sensors and their listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: BinNightConfigEntry) -> None:
    """Delete the saved schedule when the address is removed."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
