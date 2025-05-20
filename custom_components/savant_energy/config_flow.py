# custom_components/savant_energy/config_flow.py
"""
Config flow for Savant Energy integration.
Guides the user through entering connection details and options for setup.
"""

import logging
import voluptuous as vol # type: ignore

from homeassistant import config_entries # type: ignore
from homeassistant.core import callback # type: ignore

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_PORT,
    CONF_OLA_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_OLA_PORT,
    CONF_SWITCH_COOLDOWN,
    DEFAULT_SWITCH_COOLDOWN,
    CONF_DMX_TESTING_MODE,
    CONF_DMX_ADDRESS_CACHE,
    DEFAULT_DMX_TESTING_MODE,
    DEFAULT_DMX_ADDRESS_CACHE,
    DEFAULT_DISABLE_SCENE_BUILDER,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN): 
    """
    Handle the configuration flow for Savant Energy.
    Guides the user through entering connection details and options.
    """
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """
        Handle the initial step of the config flow.
        Validates user input and creates the config entry.
        """
        errors = {}
        if user_input is not None:
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
                    vol.Optional(CONF_DMX_TESTING_MODE, default=DEFAULT_DMX_TESTING_MODE): bool,
                    vol.Optional(CONF_DMX_ADDRESS_CACHE, default=DEFAULT_DMX_ADDRESS_CACHE): bool,
                    vol.Optional("disable_scene_builder", default=DEFAULT_DISABLE_SCENE_BUILDER): bool,
                }
            ),
            errors=errors,
            description_placeholders={},
        )

    def _is_valid_address(self, address):
        """
        Validate address input (must be non-empty).
        """
        return address and len(address) > 0

    def _is_valid_port(self, port):
        """
        Validate port input (must be 1-65535).
        """
        return 1 <= port <= 65535

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """
        Get the options flow handler for this integration.
        """
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """
    Handle the options flow for Savant Energy.
    Allows users to update configuration options after setup.
    """
    async def async_step_init(self, user_input=None):
        """
        Handle the initial step of the options flow.
        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        options_schema = {
            vol.Required(
                CONF_ADDRESS,
                default=self.config_entry.options.get(
                    CONF_ADDRESS,
                    self.config_entry.data.get(CONF_ADDRESS, ""),
                ),
            ): str,
            vol.Required(
                CONF_PORT,
                default=self.config_entry.options.get(
                    CONF_PORT,
                    self.config_entry.data.get(CONF_PORT, 2000),
                ),
            ): int,
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
            vol.Optional(
                CONF_DMX_TESTING_MODE,
                default=self.config_entry.options.get(
                    CONF_DMX_TESTING_MODE,
                    self.config_entry.data.get(CONF_DMX_TESTING_MODE, DEFAULT_DMX_TESTING_MODE),
                ),
            ): bool,
            vol.Optional(
                CONF_DMX_ADDRESS_CACHE,
                default=self.config_entry.options.get(
                    CONF_DMX_ADDRESS_CACHE,
                    self.config_entry.data.get(CONF_DMX_ADDRESS_CACHE, DEFAULT_DMX_ADDRESS_CACHE),
                ),
            ): bool,
            vol.Optional(
                "disable_scene_builder",
                default=self.config_entry.options.get(
                    "disable_scene_builder",
                    self.config_entry.data.get("disable_scene_builder", DEFAULT_DISABLE_SCENE_BUILDER),
                ),
            ): bool,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema),
            description_placeholders={},
        )
