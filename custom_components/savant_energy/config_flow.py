# custom_components/energy_snapshot/config_flow.py
"""Config flow for Energy Snapshot integration."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, CONF_ADDRESS, CONF_PORT, CONF_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Snapshot."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Add validation for address and port
            address = user_input.get(CONF_ADDRESS)
            port = user_input.get(CONF_PORT)
            if not self._is_valid_address(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif not self._is_valid_port(port):
                errors[CONF_PORT] = "invalid_port"
            else:
                return self.async_create_entry(title="Savant Energy", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Required(CONF_PORT, default=2000): int,  # Set default port here
                }
            ),
            errors=errors,
        )

    def _is_valid_address(self, address):
        # Implement address validation logic
        return True

    def _is_valid_port(self, port):
        # Implement port validation logic
        return 1 <= port <= 65535

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Energy Snapshot."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="Savant Energy Options", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=self.config_entry.options.get(CONF_SCAN_INTERVAL, self.config_entry.data.get(CONF_SCAN_INTERVAL, 15))): int,
                }
            )
        )