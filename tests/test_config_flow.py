"""Test real Home Assistant config and options flows."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.guernsey_bin_night.api import (
    AddressNotFound,
    CannotConnect,
    InvalidResponse,
    SearchResults,
)
from custom_components.guernsey_bin_night.const import DOMAIN


async def start_flow(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})


async def search_flow(hass):
    result = await start_flow(hass)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"postcode": "gy11aa"}
    )


async def test_postcode_to_address_to_entry(hass, mock_client):
    result = await search_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "address"
    mock_client.search.assert_awaited_once_with("GY1 1AA")
    with patch(
        "custom_components.guernsey_bin_night.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"address_id": "test-address"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "test-address"
    assert result["data"]["postcode"] == "GY1 1AA"
    assert result["title"] == "Example House, Example Lane. GY1 1AA"


async def test_invalid_postcode_is_not_sent(hass, mock_client):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"postcode": "bad"}
    )
    assert result["errors"] == {"postcode": "invalid_postcode"}
    mock_client.search.assert_not_called()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (SearchResults((), False), "no_addresses"),
        (SearchResults((), True), "too_many_results"),
    ],
)
async def test_no_complete_results(hass, mock_client, response, error):
    mock_client.search.return_value = response
    result = await search_flow(hass)
    assert result["errors"] == {"postcode": error}


@pytest.mark.parametrize(
    ("exception", "error"),
    [(CannotConnect(), "cannot_connect"), (InvalidResponse(), "invalid_response")],
)
async def test_search_failure_and_retry(hass, mock_client, exception, error):
    mock_client.search.side_effect = exception
    result = await search_flow(hass)
    assert result["errors"] == {"base": error}
    mock_client.search.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"postcode": "GY1 1AA"}
    )
    assert result["step_id"] == "address"


@pytest.mark.parametrize(
    ("exception", "errors"),
    [
        (CannotConnect(), {"base": "cannot_connect"}),
        (InvalidResponse(), {"base": "invalid_response"}),
        (AddressNotFound(), {"address_id": "address_not_found"}),
    ],
)
async def test_address_failure(hass, mock_client, exception, errors):
    result = await search_flow(hass)
    mock_client.schedule.side_effect = exception
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address_id": "test-address"}
    )
    assert result["errors"] == errors


async def test_duplicate_address(hass, mock_client, entry):
    result = await search_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address_id": "test-address"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_client.schedule.assert_not_called()


async def test_options(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 12}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"update_interval": 12}
