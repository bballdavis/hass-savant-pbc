# custom_components/energy_snapshot/config_flow.py
"""Config flow for Savant Energy integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_PORT,
    CONF_OLA_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SWITCH_COOLDOWN,
    CONF_DMX_TESTING_MODE,
    DEFAULT_SWITCH_COOLDOWN,
    DEFAULT_OLA_PORT,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Savant Energy."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Add validation for address and ports
            address = user_input.get(CONF_ADDRESS)
            port = user_input.get(CONF_PORT)
            ola_port = user_input.get(CONF_OLA_PORT)

            if not self._is_valid_address(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif not self._is_valid_port(port):
                errors[CONF_PORT] = "invalid_port"
            elif not self._is_valid_port(ola_port):
                errors[CONF_OLA_PORT] = "invalid_port"
            else:
                return self.async_create_entry(title="Savant Energy", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Required(CONF_PORT, default=2000): int,
                    vol.Required(CONF_OLA_PORT, default=DEFAULT_OLA_PORT): int,
                    vol.Optional(CONF_DMX_TESTING_MODE, default=False): bool,  # Add testing mode option
                }
            ),
            errors=errors,
        )

    def _is_valid_address(self, address):
        """Validate address input."""
        return address and len(address) > 0

    def _is_valid_port(self, port):
        """Validate port input."""
        return 1 <= port <= 65535

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Savant Energy."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = {
            # Add IP address to options
            vol.Required(
                CONF_ADDRESS,
                default=self.config_entry.options.get(
                    CONF_ADDRESS,
                    self.config_entry.data.get(CONF_ADDRESS, ""),
                ),
            ): str,
            # Add JSON feed port to options
            vol.Required(
                CONF_PORT,
                default=self.config_entry.options.get(
                    CONF_PORT,
                    self.config_entry.data.get(CONF_PORT, 2000),
                ),
            ): int,
            # Add OLA port to options
            vol.Required(
                CONF_OLA_PORT,
                default=self.config_entry.options.get(
                    CONF_OLA_PORT,
                    self.config_entry.data.get(CONF_OLA_PORT, DEFAULT_OLA_PORT),
                ),
            ): int,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(
                    CONF_SCAN_INTERVAL,
                    self.config_entry.data.get(CONF_SCAN_INTERVAL, 15),
                ),
            ): int,
            vol.Optional(
                CONF_SWITCH_COOLDOWN,
                default=self.config_entry.options.get(
                    CONF_SWITCH_COOLDOWN,
                    self.config_entry.data.get(
                        CONF_SWITCH_COOLDOWN, DEFAULT_SWITCH_COOLDOWN
                    ),
                ),
            ): int,
            # Add testing mode to options with a default of False if not set
            vol.Optional(
                CONF_DMX_TESTING_MODE,
                default=self.config_entry.options.get(
                    CONF_DMX_TESTING_MODE,
                    self.config_entry.data.get(CONF_DMX_TESTING_MODE, False),
                ),
            ): bool,
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema),
        )
