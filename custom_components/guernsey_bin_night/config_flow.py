"""Postcode lookup and address selection in the Home Assistant UI."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import (
    AddressNotFound,
    BinNightClient,
    CannotConnect,
    InvalidResponse,
    normalize_postcode,
)
from .const import (
    CONF_ADDRESS,
    CONF_ADDRESS_ID,
    CONF_POSTCODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


class BinNightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure an address without asking for an internal address ID."""

    VERSION = 1

    def __init__(self) -> None:
        self._postcode = ""
        self._addresses: dict[str, str] = {}

    def _client(self) -> BinNightClient:
        return BinNightClient(async_get_clientsession(self.hass))

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search by postcode."""
        errors = {}
        if user_input is not None:
            try:
                self._postcode = normalize_postcode(user_input[CONF_POSTCODE])
                results = await self._client().search(self._postcode)
            except ValueError:
                errors[CONF_POSTCODE] = "invalid_postcode"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidResponse:
                errors["base"] = "invalid_response"
            else:
                if results.limit_hit:
                    errors[CONF_POSTCODE] = "too_many_results"
                elif not results.addresses:
                    errors[CONF_POSTCODE] = "no_addresses"
                else:
                    self._addresses = {
                        address.id: address.name for address in results.addresses
                    }
                    return await self.async_step_address()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_POSTCODE, default=self._postcode): TextSelector()}
            ),
            errors=errors,
        )

    async def async_step_address(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the chosen address and create its config entry."""
        errors = {}
        if user_input is not None:
            address_id = user_input[CONF_ADDRESS_ID]
            if address_id not in self._addresses:
                errors[CONF_ADDRESS_ID] = "invalid_address"
            else:
                await self.async_set_unique_id(address_id)
                self._abort_if_unique_id_configured()
                try:
                    await self._client().schedule(address_id)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidResponse:
                    errors["base"] = "invalid_response"
                except AddressNotFound:
                    errors[CONF_ADDRESS_ID] = "address_not_found"
                else:
                    address = self._addresses[address_id]
                    return self.async_create_entry(
                        title=address,
                        data={
                            CONF_ADDRESS_ID: address_id,
                            CONF_ADDRESS: address,
                            CONF_POSTCODE: self._postcode,
                        },
                    )
        return self.async_show_form(
            step_id="address",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=key, label=value)
                                for key, value in self._addresses.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            description_placeholders={"postcode": self._postcode},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BinNightOptionsFlow()


class BinNightOptionsFlow(OptionsFlow):
    """Allow a bounded update interval without unnecessary API traffic."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24))
                }
            ),
        )
