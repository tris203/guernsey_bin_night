"""Test collection service response parsing and transport failures."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.guernsey_bin_night.api import (
    AddressNotFound,
    BinNightClient,
    CannotConnect,
    InvalidResponse,
    normalize_postcode,
    parse_schedule,
)


@pytest.mark.parametrize("value", ["GY1 1AA", "gy11aa", " gy1  1aa "])
def test_normalize_postcode(value):
    assert normalize_postcode(value) == "GY1 1AA"


@pytest.mark.parametrize("value", ["", "GY2", "London", "JE1 1AA", "GY1 /AA"])
def test_invalid_postcode(value):
    with pytest.raises(ValueError):
        normalize_postcode(value)


def test_schedule_sorting_and_both_service_shapes(schedule):
    assert schedule.next_collection(date(2026, 9, 27)).service_ids == ("cans",)
    assert schedule.next_collection(date(2026, 9, 28)).service_ids == ("food", "waste")
    assert schedule.next_collection(date(2026, 9, 27), "glass").date == date(
        2026, 10, 6
    )
    assert schedule.next_collection(date(2026, 10, 7)) is None


@pytest.mark.parametrize("empty", [{}, []])
def test_empty_schedule(payload, empty):
    payload["servicedates"] = empty
    assert parse_schedule(payload, "test-address").collections == ()
    payload["services"] = empty
    assert parse_schedule(payload, "test-address").services == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"addressid": "wrong-address"},
        {"services": None},
        {"services": {"food": None}},
        {"servicedates": {"not-a-date": {"services": []}}},
        {"servicedates": {"2026-09-27": {"services": "food"}}},
        {"servicedates": {"2026-09-27": {"services": ["missing"]}}},
        {"error": True},
    ],
)
def test_malformed_schedule(payload, changes):
    with pytest.raises(InvalidResponse):
        parse_schedule(payload | changes, "test-address")


def mock_session(payload, status=200):
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=payload)
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    return session, response


async def test_api_gets_schedule(payload):
    session, response = mock_session(payload)
    schedule = await BinNightClient(session).schedule("test-address")
    assert schedule.address.id == "test-address"
    assert session.get.call_args.args[0].endswith("/api/address/test-address")
    assert session.get.call_args.kwargs["timeout"].total == 20
    response.json.assert_awaited_once_with(content_type=None)


async def test_search_encoding_and_results():
    session, _ = mock_session(
        {
            "error": False,
            "limitHit": True,
            "results": [{"id": "test", "address": "Example House"}],
        }
    )
    results = await BinNightClient(session).search("GY1 1AA")
    assert results.limit_hit
    assert results.addresses[0].id == "test"
    assert session.get.call_args.args[0].endswith("/api/search/GY1%201AA")


@pytest.mark.parametrize(
    "payload", [None, {}, {"error": True}, {"results": {}}, {"results": [None]}]
)
async def test_bad_search_response(payload):
    session, _ = mock_session(payload)
    with pytest.raises(InvalidResponse):
        await BinNightClient(session).search("GY1 1AA")


async def test_missing_address():
    session, _ = mock_session({}, status=404)
    with pytest.raises(AddressNotFound):
        await BinNightClient(session).schedule("gone")


@pytest.mark.parametrize("error", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_connection_failure(error):
    session, _ = mock_session({})
    session.get.return_value.__aenter__.side_effect = error
    with pytest.raises(CannotConnect):
        await BinNightClient(session).search("GY1 1AA")


async def test_invalid_json():
    session, response = mock_session({})
    response.json.side_effect = ValueError()
    with pytest.raises(InvalidResponse):
        await BinNightClient(session).search("GY1 1AA")


async def test_http_failure():
    session, response = mock_session({})
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        MagicMock(), (), status=503
    )
    with pytest.raises(CannotConnect):
        await BinNightClient(session).search("GY1 1AA")
