"""Test loaded sensors, midnight rollover, outages and unload in real HA."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.guernsey_bin_night.api import (
    CannotConnect,
    InvalidResponse,
    parse_schedule,
)
from custom_components.guernsey_bin_night.const import DOMAIN


async def setup(hass, entry, freezer):
    await hass.config.async_set_time_zone("Europe/Guernsey")
    freezer.move_to("2026-09-27T12:00:00+01:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.states.async_all("sensor")


def next_sensor(hass):
    return next(
        state
        for state in hass.states.async_all("sensor")
        if "collections" in state.attributes
    )


async def test_entities(hass, entry, mock_client, freezer):
    states = await setup(hass, entry, freezer)
    assert len(states) == 6
    assert all(state.attributes["device_class"] == "date" for state in states)
    next_collection = next_sensor(hass)
    assert next_collection.state == "2026-09-27"
    assert next_collection.attributes["days_until"] == 0
    assert next_collection.attributes["collections"] == ["Cans, plastics, cartons"]
    glass = next(
        state for state in states if state.attributes.get("service_id") == "glass"
    )
    assert glass.state == "2026-10-06"
    assert glass.attributes["days_until"] == 9
    assert "entity_picture" not in glass.attributes
    food = next(
        state for state in states if state.attributes.get("service_id") == "food"
    )
    assert food.attributes["entity_picture"] == (
        "https://guernsey.isl-fusion.com/icon/s/example/food.png"
    )
    mock_client.schedule.assert_awaited_once()


async def test_midnight_rollover_without_network(hass, entry, mock_client, freezer):
    await setup(hass, entry, freezer)
    # Midnight is 23:00 UTC in summer; move close first to avoid interval polling.
    freezer.move_to("2026-09-27T23:59:59+01:00")
    await entry.runtime_data.async_refresh()
    calls = mock_client.schedule.await_count
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert next_sensor(hass).state == "2026-09-29"
    assert next_sensor(hass).attributes["days_until"] == 1
    assert mock_client.schedule.await_count == calls


@pytest.mark.parametrize("error", [CannotConnect(), InvalidResponse()])
async def test_failure_and_recovery(hass, entry, mock_client, freezer, error):
    await setup(hass, entry, freezer)
    updated = next_sensor(hass).attributes["last_successful_update"]
    assert not next_sensor(hass).attributes["data_stale"]
    freezer.tick(timedelta(hours=1))
    mock_client.schedule.side_effect = error
    await entry.runtime_data.async_refresh()
    assert next_sensor(hass).state == "2026-09-27"
    assert next_sensor(hass).attributes["data_stale"]
    assert next_sensor(hass).attributes["last_successful_update"] == updated
    mock_client.schedule.side_effect = None
    await entry.runtime_data.async_refresh()
    assert next_sensor(hass).state == "2026-09-27"
    assert not next_sensor(hass).attributes["data_stale"]
    assert next_sensor(hass).attributes["last_successful_update"] > updated


async def test_outage_rollover_and_exhaustion(hass, entry, mock_client, freezer):
    await setup(hass, entry, freezer)
    mock_client.schedule.side_effect = CannotConnect()
    await entry.runtime_data.async_refresh()
    updated = next_sensor(hass).attributes["last_successful_update"]
    freezer.move_to("2026-09-28T00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert next_sensor(hass).state == "2026-09-29"
    assert next_sensor(hass).attributes["days_until"] == 1
    assert next_sensor(hass).attributes["data_stale"]
    assert next_sensor(hass).attributes["last_successful_update"] == updated
    freezer.move_to("2026-10-07T00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert all(state.state == "unknown" for state in hass.states.async_all("sensor"))
    assert next_sensor(hass).attributes["collections"] == []


async def test_restores_saved_schedule_offline(hass, entry, mock_client, freezer):
    await setup(hass, entry, freezer)
    old_coordinator = entry.runtime_data
    saved = await old_coordinator.store.async_load()
    assert saved["schedule"]["addressid"] == "test-address"
    updated = next_sensor(hass).attributes["last_successful_update"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    mock_client.schedule.side_effect = CannotConnect()
    freezer.move_to("2026-09-28T12:00:00+01:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data is not old_coordinator
    assert entry.runtime_data.data.service_images == old_coordinator.data.service_images
    assert len(hass.states.async_all("sensor")) == 6
    assert next_sensor(hass).state == "2026-09-29"
    assert next_sensor(hass).attributes["data_stale"]
    assert next_sensor(hass).attributes["last_successful_update"] == updated


@pytest.mark.parametrize(
    "cached",
    [
        {},
        {"last_successful_update": "not-a-date"},
        {"last_successful_update": "2026-09-27T12:00:00"},
        {"last_successful_update": "2026-09-27T12:00:00Z", "schedule": {}},
    ],
)
async def test_invalid_cache_does_not_mask_outage(
    hass, entry, mock_client, hass_storage, cached
):
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": cached,
    }
    mock_client.schedule.side_effect = CannotConnect()
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_save_failure_keeps_live_dates(hass, entry, mock_client, freezer):
    with patch(
        "custom_components.guernsey_bin_night.coordinator.Store.async_save",
        side_effect=OSError(),
    ):
        await setup(hass, entry, freezer)
    assert next_sensor(hass).state == "2026-09-27"
    assert not next_sensor(hass).attributes["data_stale"]


async def test_unreadable_cache_fetches_live_dates(hass, entry, mock_client, freezer):
    with patch(
        "custom_components.guernsey_bin_night.coordinator.Store.async_load",
        side_effect=HomeAssistantError("Cannot read storage"),
    ):
        await setup(hass, entry, freezer)
    assert next_sensor(hass).state == "2026-09-27"
    assert not next_sensor(hass).attributes["data_stale"]


async def test_successful_empty_response_replaces_cache(
    hass, entry, mock_client, freezer, payload
):
    await setup(hass, entry, freezer)
    payload["servicedates"] = []
    mock_client.schedule.return_value = parse_schedule(payload, "test-address")
    await entry.runtime_data.async_refresh()
    assert next_sensor(hass).state == "unknown"
    assert not next_sensor(hass).attributes["data_stale"]
    mock_client.schedule.side_effect = CannotConnect()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert next_sensor(hass).state == "unknown"
    assert next_sensor(hass).attributes["data_stale"]


async def test_remove_entry_deletes_saved_schedule(
    hass, entry, mock_client, freezer, hass_storage
):
    await setup(hass, entry, freezer)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_initial_failure_retries(hass, entry, mock_client):
    mock_client.schedule.side_effect = CannotConnect("Collection service unavailable")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_scheduled_retry_backoff_and_recovery(hass, entry, mock_client, freezer):
    await setup(hass, entry, freezer)
    coordinator = entry.runtime_data
    mock_client.schedule.side_effect = CannotConnect()
    await coordinator.async_refresh()
    for minutes in (15, 30, 60, 120, 240, 360, 360):
        assert coordinator.update_interval == timedelta(minutes=minutes)
        assert next_sensor(hass).attributes["data_stale"]
        calls = mock_client.schedule.await_count
        # Nothing should request data before the retry timer expires.
        freezer.tick(timedelta(minutes=minutes, seconds=-2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert mock_client.schedule.await_count == calls
        freezer.tick(timedelta(seconds=3))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert mock_client.schedule.await_count == calls + 1
    mock_client.schedule.side_effect = None
    freezer.tick(timedelta(hours=6, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert coordinator.update_interval == timedelta(hours=24)
    assert not next_sensor(hass).attributes["data_stale"]
    # A later outage starts a fresh sequence, rather than retaining the cap.
    mock_client.schedule.side_effect = CannotConnect()
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(minutes=15)
    calls = mock_client.schedule.await_count
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(hours=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert mock_client.schedule.await_count == calls


async def test_retry_never_exceeds_custom_interval(hass, entry, mock_client, freezer):
    hass.config_entries.async_update_entry(entry, options={"update_interval": 1})
    await setup(hass, entry, freezer)
    mock_client.schedule.side_effect = InvalidResponse()
    for minutes in (15, 30, 60, 60):
        await entry.runtime_data.async_refresh()
        assert entry.runtime_data.update_interval == timedelta(minutes=minutes)
    mock_client.schedule.side_effect = None
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.update_interval == timedelta(hours=1)


async def test_successful_empty_response_does_not_retry_faster(
    hass, entry, mock_client, freezer, payload
):
    await setup(hass, entry, freezer)
    mock_client.schedule.side_effect = CannotConnect()
    await entry.runtime_data.async_refresh()
    mock_client.schedule.side_effect = None
    payload["servicedates"] = []
    mock_client.schedule.return_value = parse_schedule(payload, "test-address")
    await entry.runtime_data.async_refresh()
    assert next_sensor(hass).state == "unknown"
    assert not next_sensor(hass).attributes["data_stale"]
    assert entry.runtime_data.update_interval == timedelta(hours=24)


async def test_empty_schedule_is_unknown(hass, entry, mock_client, freezer, payload):
    payload["servicedates"] = []
    mock_client.schedule.return_value = parse_schedule(payload, "test-address")
    states = await setup(hass, entry, freezer)
    assert all(state.state == "unknown" for state in states)
    assert next_sensor(hass).attributes["collections"] == []
    assert next_sensor(hass).attributes["days_until"] is None


async def test_new_service_is_discovered(hass, entry, mock_client, freezer, payload):
    await setup(hass, entry, freezer)
    payload["services"]["new"] = {"name": "New material"}
    payload["servicedates"]["2026-09-29"]["services"] = ["new"]
    mock_client.schedule.return_value = parse_schedule(payload, "test-address")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(hass.states.async_all("sensor")) == 7


async def test_options_reload_and_unload(hass, entry, mock_client, freezer):
    await setup(hass, entry, freezer)
    hass.config_entries.async_update_entry(entry, options={"update_interval": 12})
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == timedelta(hours=12)
    assert len(hass.states.async_all("sensor")) == 6
    coordinator = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not coordinator._listeners
    calls = mock_client.schedule.await_count
    freezer.move_to("2026-09-28T00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert mock_client.schedule.await_count == calls
