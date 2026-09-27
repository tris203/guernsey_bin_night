"""Home Assistant fixtures with synthetic addresses and offline collection data."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.guernsey_bin_night.api import (
    Address,
    SearchResults,
    parse_schedule,
)
from custom_components.guernsey_bin_night.const import DOMAIN


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in Home Assistant."""
    yield


@pytest.fixture
def payload():
    """Mirror the real API's list and PHP object shapes without personal data."""
    return {
        "addressid": "test-address",
        "address": "Example House, Example Lane. GY1 1AA",
        "services": {
            "food": {
                "serviceuid": "food",
                "name": "Food",
                "imageurl": "/icon/s/example/food.png",
            },
            "glass": {"serviceuid": "glass", "name": "Glass"},
            "waste": {"serviceuid": "waste", "name": "Residual waste"},
            "paper": {"serviceuid": "paper", "name": "Paper and cardboard"},
            "cans": {"serviceuid": "cans", "name": "Cans, plastics, cartons"},
        },
        "servicedates": {
            "2026-10-04": {"services": ["paper"]},
            "2026-09-29": {"services": {"1": "food", "0": "waste"}},
            "2026-09-27": {"services": ["cans"]},
            "2026-10-06": {"services": ["food", "glass"]},
        },
    }


@pytest.fixture
def schedule(payload):
    return parse_schedule(payload, "test-address")


@pytest.fixture
def mock_client(schedule):
    """Mock the API boundary, leaving actual HA flows/coordinators/entities running."""
    client = AsyncMock()
    client.search.return_value = SearchResults(
        (
            Address("test-address", "Example House, Example Lane. GY1 1AA"),
            Address("other-address", "Other House, Example Lane. GY1 1AA"),
        ),
        False,
    )
    client.schedule.return_value = schedule
    with (
        patch(
            "custom_components.guernsey_bin_night.config_flow.BinNightClient",
            return_value=client,
        ),
        patch(
            "custom_components.guernsey_bin_night.BinNightClient", return_value=client
        ),
    ):
        yield client


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-address",
        title="Example House",
        data={
            "address_id": "test-address",
            "address": "Example House, Example Lane. GY1 1AA",
            "postcode": "GY1 1AA",
        },
    )
    entry.add_to_hass(hass)
    return entry
