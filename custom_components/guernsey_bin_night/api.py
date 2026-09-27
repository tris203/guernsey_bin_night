"""Client for the public API used by gov.gg/mybinnight."""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import BASE_URL


class BinNightError(Exception):
    """The collection service could not provide usable data."""


class CannotConnect(BinNightError):
    """The collection service could not be reached."""


class InvalidResponse(BinNightError):
    """The collection service returned an unexpected response."""


class AddressNotFound(BinNightError):
    """The address no longer exists."""


def normalize_postcode(value: str) -> str:
    """Normalize a full Guernsey postcode before searching."""
    compact = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"GY[1-9]\d?\d[A-Z]{2}", compact):
        raise ValueError("Enter a full Guernsey postcode")
    return f"{compact[:-3]} {compact[-3:]}"


@dataclass(frozen=True)
class Address:
    """An address offered by the collection service."""

    id: str
    name: str


@dataclass(frozen=True)
class SearchResults:
    """Address search results and whether the server truncated them."""

    addresses: tuple[Address, ...]
    limit_hit: bool


@dataclass(frozen=True)
class Collection:
    """Services scheduled on a bin night."""

    date: date
    service_ids: tuple[str, ...]


@dataclass(frozen=True)
class Schedule:
    """A validated schedule, independent of Home Assistant."""

    address: Address
    services: dict[str, str]
    collections: tuple[Collection, ...]
    service_images: dict[str, str] = field(default_factory=dict)

    def next_collection(
        self, today: date, service_id: str | None = None
    ) -> Collection | None:
        """Return the first matching night, including today."""
        return next(
            (
                collection
                for collection in self.collections
                if collection.date >= today
                and (service_id is None or service_id in collection.service_ids)
            ),
            None,
        )


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidResponse("Missing or invalid text field")
    return value.strip()


def parse_schedule(payload: Any, address_id: str) -> Schedule:
    """Normalize PHP's list/object service IDs and reject malformed schedules."""
    try:
        if not isinstance(payload, dict) or payload.get("error"):
            raise InvalidResponse("Invalid schedule response")
        address = Address(_text(payload["addressid"]), _text(payload["address"]))
        if address.id != address_id:
            raise InvalidResponse("Schedule belongs to a different address")
        raw_services = payload["services"]
        raw_dates = payload["servicedates"]
        # PHP serializes empty associative arrays as [].
        if raw_services == []:
            raw_services = {}
        if raw_dates == []:
            raw_dates = {}
        if not isinstance(raw_services, dict) or not isinstance(raw_dates, dict):
            raise InvalidResponse("Invalid schedule fields")
        services = {
            _text(key): _text(item["name"]) for key, item in raw_services.items()
        }
        # Images are optional; an absent image must not discard usable dates.
        service_images = {
            key: image
            for key, item in raw_services.items()
            if isinstance(image := item.get("imageurl"), str)
            and image.startswith("/icon/")
        }
        collections = []
        for day, item in raw_dates.items():
            collection_date = date.fromisoformat(day)
            service_ids = item["services"]
            if isinstance(service_ids, dict):
                service_ids = list(service_ids.values())
            if not isinstance(service_ids, list):
                raise InvalidResponse("Invalid collection services")
            ids = tuple(dict.fromkeys(_text(key) for key in service_ids))
            if any(key not in services for key in ids):
                raise InvalidResponse("Collection references an unknown service")
            if ids:
                collections.append(Collection(collection_date, ids))
        return Schedule(
            address,
            services,
            tuple(sorted(collections, key=lambda c: c.date)),
            service_images,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise InvalidResponse("Malformed schedule") from err


class BinNightClient:
    """Async client using Home Assistant's shared HTTP session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, path: str) -> Any:
        try:
            async with self._session.get(
                f"{BASE_URL}/api/{path}", timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status == 404 and path.startswith("address/"):
                    raise AddressNotFound("Address not found")
                response.raise_for_status()
                # The public endpoint sometimes labels JSON as text/html.
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            # Do not log request URLs: they contain the address ID/postcode.
            raise CannotConnect("Unable to contact the collection service") from err
        except ValueError as err:
            raise InvalidResponse(
                "The collection service returned invalid JSON"
            ) from err

    async def search(self, postcode: str) -> SearchResults:
        """Look up addresses using a full postcode."""
        payload = await self._get(f"search/{quote(postcode, safe='')}")
        try:
            if not isinstance(payload, dict) or payload.get("error"):
                raise InvalidResponse("Invalid search response")
            if not isinstance(payload["results"], list):
                raise InvalidResponse("Invalid address results")
            addresses = tuple(
                Address(_text(item["id"]), _text(item["address"]))
                for item in payload["results"]
            )
            return SearchResults(addresses, bool(payload.get("limitHit", False)))
        except (KeyError, TypeError) as err:
            raise InvalidResponse("Malformed address results") from err

    async def schedule(self, address_id: str) -> Schedule:
        """Get a schedule for a selected address."""
        return parse_schedule(
            await self._get(f"address/{quote(address_id, safe='')}"), address_id
        )
