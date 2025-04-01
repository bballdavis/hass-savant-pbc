"""Button platform for Savant Energy."""

import logging
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT

_LOGGER = logging.getLogger(__name__)

ALL_LOADS_BUTTON_NAME: Final = "All Loads On"
DEFAULT_CHANNEL_COUNT: Final = 50


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Savant Energy button."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Only add the all loads button if we have data
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        async_add_entities(
            [
                SavantAllLoadsButton(hass, coordinator),
                SavantApiCommandLogButton(hass, coordinator),
            ]
        )


class SavantAllLoadsButton(ButtonEntity):
    """Button to turn on all Savant Energy loads."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the button."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = ALL_LOADS_BUTTON_NAME
        self._attr_unique_id = f"{DOMAIN}_all_loads_on_button"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "savant_energy_controller")},
            name="Savant Energy",
            manufacturer=MANUFACTURER,
        )

    async def async_press(self) -> None:
        """Handle the button press - send command to turn on all loads."""
        # Default to 50 channels if we can't get actual count
        devices_count = DEFAULT_CHANNEL_COUNT

        # Try to determine actual count from data
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            if len(self.coordinator.data["presentDemands"]) > 0:
                devices_count = len(self.coordinator.data["presentDemands"])
            else:
                _LOGGER.debug(
                    "No devices found in data, using %s channels", devices_count
                )
        else:
            _LOGGER.debug("No device data available, using %s channels", devices_count)

        # Set all channels to 255
        channel_values = ["255"] * devices_count

        # Get IP address from config entry
        ip_address = self.coordinator.config_entry.data.get("address")
        if not ip_address:
            _LOGGER.warning("No IP address available, cannot send all loads on command")
            return

        # Get OLA port from config entry or use default
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)

        # Format the command string
        formatted_string = f'curl -X POST -d "u=1&d={",".join(channel_values)}" http://{ip_address}:{ola_port}/set_dmx'

        # Log the command
        _LOGGER.debug("Sending all loads on command: %s", formatted_string)


class SavantApiCommandLogButton(ButtonEntity):
    """Button that logs an example DMX API command."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the button."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = "DMX API Command Log"
        self._attr_unique_id = f"{DOMAIN}_dmx_api_command_log"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "savant_energy_controller")},
            name="Savant Energy",
            manufacturer=MANUFACTURER,
        )

    @property
    def icon(self) -> str:
        """Return the button icon."""
        return "mdi:console"

    async def async_press(self) -> None:
        """Handle the button press - log the curl command."""
        # Only log the curl command without executing it
        ip_address = self.coordinator.config_entry.data.get("address")
        if not ip_address:
            _LOGGER.warning(
                "No IP address available, cannot generate curl command example"
            )
            return

        # Get OLA port from config entry or use default
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)

        # Default to 50 channels if we can't get actual count
        devices_count = DEFAULT_CHANNEL_COUNT

        # Try to determine actual count from data
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            if len(self.coordinator.data["presentDemands"]) > 0:
                devices_count = len(self.coordinator.data["presentDemands"])
            else:
                _LOGGER.debug(
                    "No devices found in data, using %s channels", devices_count
                )
        else:
            _LOGGER.debug("No device data available, using %s channels", devices_count)

        channel_values = ["255"] * devices_count
        curl_command = f'curl -X POST -d "u=1&d={",".join(channel_values)}" http://{ip_address}:{ola_port}/set_dmx'
        _LOGGER.info("DMX API command example: %s", curl_command)
